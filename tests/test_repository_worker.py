import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_repository_keys as fixture
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app import repository_worker as worker
from app.models import (
    ProjectJob,
    ProjectDeployKey,
    OrcaProject,
    Base,
    ProjectOwner,
    ProjectRepository,
)
from app.ops import backup, restore, BUSINESS_V3
from app.storage import Storage
from app.config import Settings


class WorkerTests(unittest.TestCase):
    setUp, tearDown, client, uid, project = (
        fixture.RepositoryKeyTests.setUp,
        fixture.RepositoryKeyTests.tearDown,
        fixture.RepositoryKeyTests.client,
        fixture.RepositoryKeyTests.uid,
        fixture.RepositoryKeyTests.project,
    )

    def child(self, args, timeout):
        if args[0] == "mkdir":
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        elif args[0] == "python3":
            return subprocess.run(
                [sys.executable, *args[1:]],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        elif args[0] == "ssh-keygen":
            return subprocess.run(
                [self.ssh, *args[1:]], capture_output=True, text=True, timeout=timeout
            )
        elif args[0] == "cat":
            return SimpleNamespace(
                returncode=0, stdout=Path(args[-1]).read_text(), stderr=""
            )
        elif args[0] == "git":
            if "clone" in args:
                Path(args[-1]).mkdir()
                self.origins[args[-1]] = args[-2]
            elif "get-url" in args:
                return SimpleNamespace(
                    returncode=0, stdout=self.origins.get(args[2], ""), stderr=""
                )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def run_job(self):
        with patch.object(worker, "PROJECTS", self.projects), patch.object(
            worker, "KEYS", self.keys
        ), patch.object(worker, "available_disk", return_value=True):
            self.assertTrue(worker.run_one(self.app.state.engine, self.child))

    def test_revalidation_ends_old_snapshot_after_ownership_changes(self):
        pid = self.project()
        self.client("amy").post(f"/api/projects/{pid}/deploy-key/create")
        with self.app.state.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        with Session(self.app.state.engine) as db:
            db.connection().exec_driver_sql("BEGIN")
            job = db.scalar(
                select(ProjectJob).where(
                    ProjectJob.project_id == pid, ProjectJob.kind == "key_create"
                )
            )
            # Hold a real SQLite read snapshot, like a MySQL repeatable-read transaction.
            db.get(ProjectOwner, pid)
            response = self.client("amy").put(
                f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")}
            )
            self.assertEqual(response.status_code, 200, response.text)
            with self.assertRaises(ValueError):
                worker.authorize(db, job)

    def test_real_temporary_key_registration_and_local_removal_flow(self):
        self.ssh = shutil.which("ssh-keygen")
        if not self.ssh:
            self.skipTest("OpenSSH key generator unavailable")
        self.projects = Path(self.tmp.name) / "projects"
        self.projects.mkdir()
        self.keys = Path(self.tmp.name) / "keys"
        self.origins = {}
        pid = self.project()
        amy = self.client("amy")
        amy.post(f"/api/projects/{pid}/deploy-key/create")
        self.run_job()
        state = amy.get(f"/api/projects/{pid}/repository").json()
        self.assertEqual(state["key"]["state"], "awaiting_registration")
        self.assertTrue(state["key"]["public_key"].startswith("ssh-ed25519 "))
        self.assertFalse(
            "PRIVATE KEY" in json.dumps(state), "API exposed private key material"
        )
        config = (self.keys / f"p{pid}.conf").read_text()
        self.assertIn("HostName ssh.github.com", config)
        self.assertIn("Port 443", config)
        self.assertIn("StrictHostKeyChecking yes", config)
        if sys.platform != "win32":
            self.assertEqual(
                (self.keys / f"p{pid}-g1.key").stat().st_mode & 0o777, 0o600
            )
        amy.post(f"/api/projects/{pid}/deploy-key/verify")
        self.run_job()
        state = amy.get(f"/api/projects/{pid}/repository").json()
        self.assertEqual(state["key"]["state"], "read_verified")
        self.assertEqual(state["state"], "linked")
        self.assertFalse(state["key"]["write_verified"])
        folder = self.projects / state["folder"]
        self.assertTrue(folder.exists())
        amy.post(f"/api/projects/{pid}/deploy-key/remove")
        self.run_job()
        self.assertFalse((self.keys / f"p{pid}-g1.key").exists())
        self.assertTrue(folder.exists())

    def test_v4_restore_preserves_owner_and_requires_new_credential_registration(self):
        pid = self.project()
        with Session(self.app.state.engine) as db:
            db.add(
                ProjectDeployKey(
                    project_id=pid,
                    generation=4,
                    public_key="public-fixture",
                    fingerprint="SHA256:fixture",
                    state="read_verified",
                    created="t",
                )
            )
            db.commit()
        archive = backup(self.app.state.engine, self.app.state.storage)
        target = create_engine(f"sqlite:///{self.tmp.name}/restore4.db")
        Base.metadata.create_all(target)
        try:
            restore(
                target,
                Storage(Settings(data_dir=Path(self.tmp.name) / "restore4")),
                archive,
            )
            with Session(target) as db:
                self.assertEqual(db.get(ProjectOwner, pid).user_id, self.uid("amy"))
                self.assertEqual(
                    db.get(ProjectDeployKey, pid).state, "needs_registration"
                )
                self.assertEqual(db.get(ProjectDeployKey, pid).public_key, "")
                self.assertEqual(
                    db.get(ProjectRepository, pid).state, "restore_required"
                )
                self.assertIsNone(db.scalar(select(ProjectJob)))
        finally:
            target.dispose()

    def test_v3_backup_still_restores_after_v4_is_added(self):
        self.project()
        payload = json.loads(backup(self.app.state.engine, self.app.state.storage))
        payload["version"] = 3
        names = {m.__tablename__ for m in BUSINESS_V3}
        payload["tables"] = {k: v for k, v in payload["tables"].items() if k in names}
        target = create_engine(f"sqlite:///{self.tmp.name}/restore3.db")
        Base.metadata.create_all(target)
        try:
            result = restore(
                target,
                Storage(Settings(data_dir=Path(self.tmp.name) / "restore3")),
                json.dumps(payload).encode(),
            )
            self.assertEqual(result["projects"], 1)
        finally:
            target.dispose()

    def test_failed_command_does_not_publish_raw_stderr(self):
        pid = self.project()
        self.client("amy").post(f"/api/projects/{pid}/deploy-key/create")

        def fail(args, timeout):
            return SimpleNamespace(
                returncode=1, stdout="", stderr="private-fixture-value"
            )

        worker.run_one(self.app.state.engine, fail)
        response = self.client("amy").get(f"/api/projects/{pid}/repository")
        self.assertNotIn("private-fixture-value", response.text)
        self.assertEqual(response.json()["jobs"][0]["state"], "failed")
