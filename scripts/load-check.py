"""Reproducible isolated local load probe, never connects to the production database.

python scripts/load-check.py --output .local/load-result.json
Numbers describe this machine and SQLite/ASGI only; they are not EC2/RDS capacity claims.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import password_hash
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        app = create_app(
            Settings(
                database_url=f"sqlite:///{temp}/load.db",
                data_dir=Path(temp),
                origin="http://testserver",
                secure_cookies=False,
            )
        )
        clients = []
        try:
            with Session(app.state.engine) as db:
                encoded = password_hash("Isolated-load-test-only")
                db.add_all(
                    [
                        User(username=f"load{i}", password_hash=encoded, role="member")
                        for i in range(100)
                    ]
                )
                db.commit()
            for i in range(100):
                c = TestClient(app)
                c.headers["Origin"] = "http://testserver"
                assert (
                    c.post(
                        "/api/login",
                        json={
                            "username": f"load{i}",
                            "password": "Isolated-load-test-only",
                        },
                    ).status_code
                    == 200
                )
                assert c.get("/api/session").status_code == 200
                clients.append(c)
            results = []

            def probe(c):
                start = time.perf_counter()
                statuses = [
                    c.get(p).status_code
                    for p in ("/api/changes", "/api/chat/people", "/api/notices")
                ]
                return {
                    "elapsed": time.perf_counter() - start,
                    "errors": sum(x != 200 for x in statuses),
                }

            for concurrency in (10, 30, 100):
                start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    rows = list(pool.map(probe, clients[:concurrency]))
                times = sorted(r["elapsed"] for r in rows)
                result = {
                    "users": concurrency,
                    "requests": concurrency * 3,
                    "errors": sum(r["errors"] for r in rows),
                    "elapsed_s": round(time.perf_counter() - start, 3),
                    "user_roundtrip_p95_s": round(
                        times[min(len(times) - 1, int(len(times) * 0.95))], 3
                    ),
                }
                results.append(result)
                print(json.dumps(result), flush=True)
            args.output.write_text(
                json.dumps(
                    {
                        "scope": "isolated local SQLite/ASGI, 3 sequential GETs per user",
                        "results": results,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if any(r["errors"] for r in results):
                raise SystemExit(1)
        finally:
            for c in clients:
                c.close()
            app.state.engine.dispose()


if __name__ == "__main__":
    main()
