import tempfile
import unittest
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.config import Settings
from app.models import Base, Project, Note, Attachment, Event
from app.storage import Storage
from app.ops import backup, restore, monitor
from unittest.mock import patch


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name))
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/source.db")
        Base.metadata.create_all(self.engine)
        self.storage = Storage(self.settings)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def test_backup_restores_notes_and_exact_file_content_into_empty_database(self):
        key = "attachments/" + "a" * 32
        self.storage.put(key, b"restore this byte for byte", "text/plain")
        with Session(self.engine) as db:
            db.add(Project(id=1, name="Recovery demo", description="", created="2026-11-10T00:00:00+00:00"))
            db.flush()
            db.add(Note(project_id=1, author="tester", body="복원 시험", created="2026-11-10T00:00:00+00:00"))
            db.add(Attachment(project_id=1, name="test.txt", key=key, size=29, media_type="text/plain"))
            db.commit()
        archive = backup(self.engine, self.storage)
        target = create_engine(f"sqlite:///{self.tmp.name}/restored.db")
        Base.metadata.create_all(target)
        restored_storage = Storage(Settings(data_dir=Path(self.tmp.name) / "restored"))
        try:
            result = restore(target, restored_storage, archive)
            self.assertEqual(result["projects"], 1)
            with Session(target) as db:
                self.assertEqual(db.scalar(select(Note)).body, "복원 시험")
            self.assertEqual(restored_storage.get(key), b"restore this byte for byte")
            with self.assertRaises(ValueError):
                restore(target, restored_storage, archive)
        finally:
            target.dispose()

    def test_failed_backup_records_failure(self):
        class BrokenStorage:
            def put(self, *args):
                raise OSError("unavailable")
        with self.assertRaises(OSError):
            backup(self.engine, BrokenStorage())
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(Event)).state, "failed")

    def test_monitor_records_outage_and_recovery(self):
        bad = monitor(self.engine, self.settings.data_dir, probe=lambda: False)
        good = monitor(self.engine, self.settings.data_dir, probe=lambda: True)
        self.assertEqual(bad["state"], "failed")
        self.assertEqual(good["state"], "ok")
        with Session(self.engine) as db:
            self.assertEqual(len(list(db.scalars(select(Event)))), 2)

    def test_restore_rejects_corruption_before_writing(self):
        with self.assertRaises(ValueError):
            restore(self.engine, self.storage, b'{"version": 99}')
        with Session(self.engine) as db:
            self.assertIsNone(db.scalar(select(Project)))

    def test_object_paths_reject_traversal(self):
        with self.assertRaises(ValueError):
            self.storage.put("../../escape", b"bad", "text/plain")

    def test_backup_rejects_inventory_over_budget_before_loading_objects(self):
        with Session(self.engine) as db:
            db.add(Project(id=1, name="Budget", description="", created="2026-11-10T00:00:00+00:00"))
            db.flush()
            db.add(Attachment(project_id=1, name="huge.txt", key="attachments/" + "b" * 32, size=64 * 1024 * 1024, media_type="text/plain"))
            db.commit()
        with patch.object(self.storage, "get", side_effect=AssertionError("Object read before size budget check")):
            with self.assertRaises(ValueError):
                backup(self.engine, self.storage)

    def test_backup_budget_uses_actual_object_size_not_only_database_metadata(self):
        with Session(self.engine) as db:
            db.add(Project(id=1, name="Actual size", description="", created="2026-11-10T00:00:00+00:00"))
            db.flush()
            for i in range(20):
                db.add(Attachment(project_id=1, name="test.txt", key=f"attachments/{i:032x}", size=1, media_type="text/plain"))
            db.commit()
        with patch.object(self.storage, "get", return_value=b"x" * 1024 * 1024) as read:
            with self.assertRaises(ValueError):
                backup(self.engine, self.storage)
            self.assertLessEqual(read.call_count, 13)
