import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import OrcaLinkRequest, OrcaProject
from app.orca_admin import normalize_repo, valid_folder
from app.security import create_user

PW = "A-team-test-password-93"
ROOT = Path(__file__).resolve().parents[1]


def load_worker():
    spec = importlib.util.spec_from_file_location("orca_link_worker", ROOT / "deploy" / "orca-link-worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OrcaAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        create_user(self.app.state.engine, "boss", PW, "admin")
        create_user(self.app.state.engine, "amy", PW, "member")
        self.c = self.login("boss")
        self.pid = self.c.post("/api/projects", json={"name": "club-site"}).json()["id"]

    def login(self, name):
        c = TestClient(self.app); c.headers["Origin"] = "http://testserver"
        r = c.post("/api/login", json={"username": name, "password": PW}); c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c

    def tearDown(self):
        self.c.close(); self.app.state.engine.dispose(); self.tmp.cleanup()

    def test_url_and_folder_validation(self):
        self.assertEqual(normalize_repo("https://github.com/kosmos-s/aws-teamproject.git"), ("https://github.com/kosmos-s/aws-teamproject", "aws-teamproject"))
        self.assertEqual(normalize_repo(" https://github.com/a/b/ ")[0], "https://github.com/a/b")
        for bad in ["http://github.com/a/b", "https://gitlab.com/a/b", "https://github.com/a/b;rm -rf", "https://github.com/a",
                    "https://github.com/a/b/tree/main", "git@github.com:a/b.git", "https://github.com/../..", "https://github.com/a/.."]:
            with self.assertRaises(ValueError, msg=bad):
                normalize_repo(bad)
        self.assertTrue(valid_folder("my-repo_1.x"))
        for bad in ["", ".", "..", "../x", "a/b", "-rf", "a..b", " x"]:
            self.assertFalse(valid_folder(bad), bad)

    def test_request_flow_and_refusals(self):
        r = self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/kosmos-s/club.git"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["folder"], "club")
        self.assertEqual(self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/x/y"}).status_code, 409)
        self.assertEqual(self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://evil.com/x/y"}).status_code, 422)
        self.assertEqual(self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/x/y", "folder": "../etc"}).status_code, 422)
        self.assertEqual(self.c.post("/api/admin/orca-links", json={"project_id": 999, "repository_url": "https://github.com/x/y"}).status_code, 404)
        overview = self.c.get("/api/admin/orca").json()
        self.assertEqual(overview["requests"][0]["state"], "pending")
        amy = self.login("amy")
        self.assertEqual(amy.get("/api/admin/orca").status_code, 403)
        self.assertEqual(amy.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/x/y"}).status_code, 403)
        amy.close()

    def test_unlink(self):
        with Session(self.app.state.engine) as db:
            db.add(OrcaProject(project_id=self.pid, label="club", repository_url="https://github.com/a/club")); db.commit()
        self.assertTrue(self.c.get("/api/projects").json()[0]["orca_available"])
        self.assertEqual(self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/a/club"}).status_code, 409)
        self.assertEqual(self.c.delete(f"/api/admin/orca-projects/{self.pid}").status_code, 200)
        self.assertFalse(self.c.get("/api/projects").json()[0]["orca_available"])
        self.assertEqual(self.c.delete(f"/api/admin/orca-projects/{self.pid}").status_code, 404)

    def run_worker(self, fake_run, existing_origin=None, folder_exists=False):
        worker = load_worker()
        projects = Path(self.tmp.name) / "projects"; projects.mkdir(exist_ok=True)
        if folder_exists:
            (projects / "club").mkdir()
        worker.PROJECTS = projects
        with Session(self.app.state.engine) as db:
            req = db.get(OrcaLinkRequest, 1)
            with mock.patch.object(worker, "as_orca", side_effect=fake_run), \
                 mock.patch.object(worker, "origin_of", return_value=existing_origin):
                try:
                    detail, ok = worker.process(db, req), True
                except RuntimeError as exc:
                    detail, ok = str(exc), False
            db.commit()
        return detail, ok

    def test_worker_clones_registers_and_links(self):
        self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/kosmos-s/club"})
        calls = []
        def fake(args, timeout):
            calls.append(args); return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")
        detail, ok = self.run_worker(fake)
        self.assertTrue(ok, detail)
        self.assertEqual(calls[0][:3], ["git", "clone", "--"])
        self.assertEqual(calls[0][3], "https://github.com/kosmos-s/club")
        self.assertEqual(calls[1][:3], ["orca-ide", "repo", "add"])
        self.assertTrue(self.c.get("/api/projects").json()[0]["orca_available"])

    def test_worker_reports_clone_failure_without_linking(self):
        self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/kosmos-s/club"})
        detail, ok = self.run_worker(lambda a, t: SimpleNamespace(returncode=128, stdout="", stderr="fatal: repository not found"))
        self.assertFalse(ok)
        self.assertIn("clone 실패", detail)
        self.assertFalse(self.c.get("/api/projects").json()[0]["orca_available"])

    def test_worker_refuses_folder_of_another_repo(self):
        self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/kosmos-s/club"})
        detail, ok = self.run_worker(lambda a, t: SimpleNamespace(returncode=0, stdout="", stderr=""),
                                     existing_origin="https://github.com/other/club", folder_exists=True)
        self.assertFalse(ok)
        self.assertIn("다른 저장소", detail)

    def test_worker_reuses_same_repo_checkout(self):
        self.c.post("/api/admin/orca-links", json={"project_id": self.pid, "repository_url": "https://github.com/kosmos-s/club"})
        calls = []
        def fake(args, timeout):
            calls.append(args); return SimpleNamespace(returncode=0, stdout="", stderr="")
        detail, ok = self.run_worker(fake, existing_origin="https://github.com/kosmos-s/club", folder_exists=True)
        self.assertTrue(ok, detail)
        self.assertEqual([c[0] for c in calls], ["orca-ide"])


if __name__ == "__main__":
    unittest.main()
