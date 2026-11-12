"""Operator-only real backup + isolated FK-enforced restore; outputs counts only."""

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, event
from app.main import create_app
from app.models import Base
from app.config import Settings
from app.ops import backup, restore
from app.storage import Storage


def main():
    settings = Settings.from_env()
    app = create_app(settings)
    try:
        payload = backup(app.state.engine, app.state.storage)
        with tempfile.TemporaryDirectory(
            prefix="release-restore-", dir=settings.data_dir
        ) as folder:
            path = Path(folder)
            target = create_engine(f"sqlite:///{path.as_posix()}/restore.db")

            @event.listens_for(target, "connect")
            def enforce_foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")

            try:
                Base.metadata.create_all(target)
                counts = restore(
                    target, Storage(Settings(data_dir=path / "objects")), payload
                )
                print(
                    f"Backup v3 and isolated restore verified: {len(counts)} tables; {sum(counts.values())} rows; {len(payload)} bytes"
                )
            finally:
                target.dispose()
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
