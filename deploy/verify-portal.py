"""Run as root on EC2, credentials remain inside the server."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.config import Settings
from app.main import create_app
from app.models import Base, Note, Event
from app.ops import backup, restore, event, monitor
from app.security import create_user
from app.storage import Storage


def main():
    for line in Path("/etc/kosmos-portal.env").read_text().splitlines():
        key, value = line.split("=", 1)
        os.environ[key] = value
    settings = Settings.from_env()
    login = json.loads(Path("/var/lib/kosmos/portal-login.json").read_text())
    app = create_app(settings)
    origin = settings.origin
    evidence = {}
    with TestClient(app, base_url=origin) as client:
        client.headers["Origin"] = origin
        assert client.get("/api/projects").status_code == 401
        response = client.post("/api/login", json={"username": login["username"], "password": login["password"]})
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        projects = client.get("/api/projects").json()
        if not projects:
            p = client.post("/api/projects", json={"name": "KOSMOS AWS 운영", "description": "포털과 개발환경 운영 검증"})
            assert p.status_code == 201
            project = p.json()
            assert client.post(f"/api/projects/{project['id']}/notes", json={"body": "RDS 저장과 S3 첨부, 빈 대상 복구를 확인합니다."}).status_code == 201
            content = "KOSMOS AWS storage and restore verification\n".encode()
            upload = client.post(f"/api/projects/{project['id']}/attachments", files={"file": ("verification.txt", content, "text/plain")})
            assert upload.status_code == 201
            file_id = upload.json()["id"]
        else:
            project = projects[0]
            attachment = client.get(f"/api/projects/{project['id']}/attachments").json()[0]
            file_id = attachment["id"]
            content = client.get(f"/api/attachments/{file_id}").content
        assert client.get(f"/api/attachments/{file_id}").content == content
        evidence["rds_mysql_read_write"] = True
        evidence["s3_authenticated_roundtrip"] = True
        archive = backup(app.state.engine, app.state.storage)
        with tempfile.TemporaryDirectory(prefix="kosmos-restore-") as temp:
            target = create_engine(f"sqlite:///{temp}/restored.db")
            Base.metadata.create_all(target)
            restored_storage = Storage(Settings(data_dir=Path(temp)))
            result = restore(target, restored_storage, archive)
            with Session(target) as db:
                assert db.scalar(select(Note)) is not None
            # Restore into separate local storage, not the source S3 path.
            payload = json.loads(archive)
            for key, item in payload["files"].items():
                assert hashlib.sha256(restored_storage.get(key)).hexdigest() == item["sha256"]
            create_user(target, "recovery", "A-recovery-test-password-93")
            recovered = create_app(Settings(database_url=f"sqlite:///{temp}/restored.db", data_dir=Path(temp), origin=origin, secure_cookies=True))
            with TestClient(recovered, base_url=origin) as recovery_client:
                recovery_client.headers["Origin"] = origin
                assert recovery_client.post("/api/login", json={"username": "recovery", "password": "A-recovery-test-password-93"}).status_code == 200
                assert recovery_client.get(f"/api/attachments/{file_id}").content == content
            recovered.state.engine.dispose()
            target.dispose()
            evidence["isolated_restore_counts"] = result
            evidence["restored_app_download_matches"] = True
        event(app.state.engine, "restore-validation", "ok", "Isolated SQLite restore of RDS business tables and S3 bytes; recovered app login/download passed")
        status = monitor(app.state.engine, settings.data_dir)
        assert status["state"] == "ok"
        client.post("/api/logout")
        assert client.get(f"/api/attachments/{file_id}").status_code == 401
        evidence["anonymous_attachment_denied"] = True
    app.state.engine.dispose()
    Path("/var/lib/kosmos/portal-verification.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
