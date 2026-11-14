import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_suite as fixture
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ProjectJob, ProjectDeployKey, OrcaProject, ProjectOwner
from app.ops import backup, restore


class RepositoryKeyTests(unittest.TestCase):
    setUp, tearDown, client, uid = (
        fixture.SuiteTests.setUp,
        fixture.SuiteTests.tearDown,
        fixture.SuiteTests.client,
        fixture.SuiteTests.uid,
    )

    def project(self):
        amy = self.client("amy")
        pid = amy.post(
            "/api/projects",
            json={"name": "Repo", "repository_url": "https://github.com/a/repo"},
        ).json()["id"]
        with Session(self.app.state.engine) as db:
            for j in db.scalars(select(ProjectJob)):
                j.state = "done"
            db.commit()
        return pid

    def test_transfer_preserves_disconnect_cleanup(self):
        pid = self.project()
        amy = self.client("amy")
        amy.post(f"/api/projects/{pid}/deploy-key/create")
        self.assertEqual(amy.delete(f"/api/projects/{pid}/repository").status_code, 200)
        self.assertEqual(
            amy.put(
                f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")}
            ).status_code,
            200,
        )
        with Session(self.app.state.engine) as db:
            cleanup = db.scalar(select(ProjectJob).where(ProjectJob.cleanup == 1))
            self.assertEqual(cleanup.state, "pending")

    def test_new_connection_rejects_pending_legacy_request(self):
        pid = (
            self.client("amy")
            .post("/api/projects", json={"name": "Legacy queue"})
            .json()["id"]
        )
        legacy = self.client("boss").post(
            "/api/admin/orca-links",
            json={"project_id": pid, "repository_url": "https://github.com/a/old"},
        )
        self.assertEqual(legacy.status_code, 201, legacy.text)
        response = self.client("amy").put(
            f"/api/projects/{pid}/repository",
            json={"repository_url": "https://github.com/a/new"},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_legacy_worker_rejects_managed_repository_before_commands(self):
        from app.models import OrcaLinkRequest

        pid = self.project()
        spec = importlib.util.spec_from_file_location(
            "legacy_guard_worker", Path("deploy/orca-link-worker.py")
        )
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        with Session(self.app.state.engine) as db:
            req = OrcaLinkRequest(
                project_id=pid,
                repository_url="https://github.com/a/old",
                folder="legacy-old",
                state="running",
                detail="",
                requested_by="boss",
                created="t",
            )
            db.add(req)
            db.commit()
            with patch.object(
                worker,
                "as_orca",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as child:
                with self.assertRaises(RuntimeError):
                    worker.process(db, req)
                child.assert_not_called()

    def test_only_manager_gets_public_key_and_operations(self):
        pid = self.project()
        amy, ben = self.client("amy"), self.client("ben")
        self.assertEqual(
            ben.post(f"/api/projects/{pid}/deploy-key/create").status_code, 403
        )
        self.assertEqual(ben.get(f"/api/projects/{pid}/repository").status_code, 403)
        self.assertEqual(
            amy.post(f"/api/projects/{pid}/deploy-key/create").status_code, 200
        )
        result = amy.get(f"/api/projects/{pid}/repository").json()
        self.assertFalse(result["key"]["write_verified"])
        self.assertNotIn("private_key", result["key"])
        self.assertEqual(
            amy.post(f"/api/projects/{pid}/deploy-key/create").status_code, 409
        )

    def test_transfer_cancels_pending_key_operation(self):
        pid = self.project()
        amy = self.client("amy")
        amy.post(f"/api/projects/{pid}/deploy-key/create")
        amy.put(f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")})
        with Session(self.app.state.engine) as db:
            job = db.scalar(select(ProjectJob).where(ProjectJob.kind == "key_create"))
            self.assertEqual(job.state, "cancelled")

    def test_worker_child_does_not_inherit_database_or_cloud_secrets(self):
        spec = importlib.util.spec_from_file_location(
            "link_worker", Path("deploy/orca-link-worker.py")
        )
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        fake_pwd = SimpleNamespace(getpwnam=lambda _: SimpleNamespace(pw_uid=1001))
        with patch.dict(sys.modules, {"pwd": fake_pwd}), patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "private-fixture",
                "AWS_SECRET_ACCESS_KEY": "private-fixture",
            },
        ), patch.object(
            worker.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ) as run:
            worker.as_orca(["git", "--version"], 10)
        env = run.call_args.kwargs.get("env", {})
        self.assertTrue(env)
        self.assertNotIn("DATABASE_URL", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("private-fixture", repr(run.call_args))

    def test_owner_backup_v4_preserves_ownership_without_private_key_or_live_jobs(self):
        pid = self.project()
        self.client("amy").post(f"/api/projects/{pid}/deploy-key/create")
        payload = json.loads(backup(self.app.state.engine, self.app.state.storage))
        self.assertEqual(payload["version"], 4)
        self.assertEqual(
            payload["tables"]["project_owners"][0]["user_id"], self.uid("amy")
        )
        self.assertNotIn("project_jobs", payload["tables"])
        self.assertNotIn("private_key", json.dumps(payload))

    def test_fixed_worker_links_and_rejects_stale_owner(self):
        from app import repository_worker

        pid = self.project()
        with Session(self.app.state.engine) as db:
            job = db.scalar(select(ProjectJob))
            job.state = "pending"
            db.commit()
            calls = []

            def child(args, timeout):
                calls.append(args)
                if "clone" in args:
                    Path(args[-1]).mkdir()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            root = Path(self.tmp.name) / "projects"
            root.mkdir()
            with patch.object(repository_worker, "PROJECTS", root), patch.object(
                repository_worker, "available_disk", return_value=True
            ):
                state = repository_worker.process(db, job, child)
            self.assertEqual(state, "done")
            self.assertIsNotNone(db.get(OrcaProject, pid))
            self.assertTrue(any("clone" in args for args in calls))
            db.commit()
        self.client("amy").put(
            f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")}
        )
        with Session(self.app.state.engine) as db:
            job = db.scalar(select(ProjectJob))
            job.state = "pending"
            db.commit()
            with patch.object(repository_worker, "available_disk", return_value=True):
                with self.assertRaises(ValueError):
                    repository_worker.process(db, job, lambda *a: None)
