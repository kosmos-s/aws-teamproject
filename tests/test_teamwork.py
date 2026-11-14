import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import OrcaLinkRequest
from app.ops import backup, restore
from app.security import create_user
from app.storage import Storage

PW = "A-team-test-password-93"


class TeamworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False)
        self.app = create_app(self.settings)
        for name, role in [("boss", "admin"), ("amy", "member"), ("ben", "member"), ("gus", "viewer")]:
            create_user(self.app.state.engine, name, PW, role)
        self.clients = {}

    def client(self, name, password=PW):
        if name not in self.clients:
            c = TestClient(self.app); c.headers["Origin"] = "http://testserver"
            r = c.post("/api/login", json={"username": name, "password": password})
            self.assertEqual(r.status_code, 200, r.text)
            c.headers["X-CSRF-Token"] = r.json()["csrf"]
            self.clients[name] = c
        return self.clients[name]

    def uid(self, name):
        return next(u["id"] for u in self.client("boss").get("/api/admin/users").json() if u["username"] == name)

    def tearDown(self):
        for c in self.clients.values():
            c.close()
        self.app.state.engine.dispose(); self.tmp.cleanup()

    def test_account_lockout_independent_of_ip(self):
        def from_ip(i):
            c = TestClient(self.app, client=(f"10.0.0.{i}", 5000)); c.headers["Origin"] = "http://testserver"; return c
        codes = []
        for i in range(9):
            c = from_ip(i); codes.append(c.post("/api/login", json={"username": "amy", "password": "wrong"}).status_code); c.close()
        self.assertEqual(codes[:8], [401] * 8)
        self.assertEqual(codes[8], 429)
        c = from_ip(50)
        self.assertEqual(c.post("/api/login", json={"username": "amy", "password": PW}).status_code, 429)
        self.assertEqual(c.post("/api/login", json={"username": "ben", "password": PW}).status_code, 200)
        c.close()

    def test_note_edit_delete_permissions(self):
        amy, ben, boss, gus = self.client("amy"), self.client("ben"), self.client("boss"), self.client("gus")
        pid = amy.post("/api/projects", json={"name": "P"}).json()["id"]
        nid = amy.post(f"/api/projects/{pid}/notes", json={"body": "first"}).json()["id"]
        self.assertEqual(ben.patch(f"/api/notes/{nid}", json={"body": "hack"}).status_code, 403)
        self.assertEqual(gus.patch(f"/api/notes/{nid}", json={"body": "hack"}).status_code, 403)
        self.assertEqual(amy.patch(f"/api/notes/{nid}", json={"body": "  edited  "}).status_code, 200)
        note = amy.get("/api/notes").json()[0]
        self.assertEqual(note["body"], "edited"); self.assertIsNotNone(note["edited"])
        self.assertEqual(amy.patch(f"/api/notes/{nid}", json={"body": "  "}).status_code, 422)
        self.assertEqual(ben.delete(f"/api/notes/{nid}").status_code, 403)
        self.assertEqual(boss.delete(f"/api/notes/{nid}").status_code, 200)
        self.assertEqual(amy.get("/api/notes").json(), [])
        self.assertEqual(amy.delete(f"/api/notes/{nid}").status_code, 404)

    def test_project_archive_owner_or_admin_only(self):
        amy, boss = self.client("amy"), self.client("boss")
        pid = amy.post("/api/projects", json={"name": "Old"}).json()["id"]
        self.assertEqual(self.client('ben').post(f"/api/projects/{pid}/archive").status_code,403)
        self.assertEqual(amy.post(f"/api/projects/{pid}/archive").status_code, 200)
        self.assertEqual(boss.post(f"/api/projects/{pid}/archive").status_code, 200)
        self.assertTrue(amy.get("/api/projects").json()[0]["archived"])
        self.assertEqual(boss.delete(f"/api/projects/{pid}/archive").status_code, 200)
        self.assertFalse(amy.get("/api/projects").json()[0]["archived"])
        self.assertEqual(boss.delete(f"/api/projects/{pid}/archive").status_code, 404)

    def test_groups_and_group_chat(self):
        boss, amy, ben = self.client("boss"), self.client("amy"), self.client("ben")
        gid = boss.post("/api/admin/groups", json={"name": "디자인팀", "description": "UI"}).json()["id"]
        self.assertEqual(boss.post("/api/admin/groups", json={"name": "디자인팀"}).status_code, 409)
        self.assertEqual(amy.post("/api/admin/groups", json={"name": "x"}).status_code, 403)
        self.assertEqual(boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy"), 9999]}).status_code, 404)
        self.assertEqual(boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy")]}).status_code, 200)
        self.assertEqual(amy.post(f"/api/chat/group/{gid}", json={"body": "팀 회의 3시"}).status_code, 201)
        self.assertEqual(ben.get(f"/api/chat/group/{gid}").status_code, 404)
        self.assertEqual(ben.post(f"/api/chat/group/{gid}", json={"body": "x"}).status_code, 404)
        self.assertEqual(ben.get("/api/chat/people").json()["groups"], [])
        boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy"), self.uid("ben")]})
        g = ben.get("/api/chat/people").json()["groups"][0]
        self.assertEqual((g["name"], g["members"], g["unread"]), ("디자인팀", 2, 1))
        self.assertEqual([m["body"] for m in ben.get(f"/api/chat/group/{gid}").json()], ["팀 회의 3시"])
        self.assertEqual(ben.get("/api/chat/people").json()["groups"][0]["unread"], 0)
        users = {u["username"]: u for u in boss.get("/api/admin/users").json()}
        self.assertEqual(users["amy"]["groups"], ["디자인팀"])
        self.assertEqual(boss.delete(f"/api/admin/groups/{gid}").status_code, 200)
        self.assertEqual(amy.get(f"/api/chat/group/{gid}").status_code, 404)

    def test_bulk_invite_and_first_login(self):
        boss = self.client("boss")
        r = boss.post("/api/admin/users/bulk", json={"text": "kim.minsu,member,디자인팀\nlee.jiwon,viewer\n# comment\nbad name\namy\npark.hana,owner"})
        self.assertEqual(r.status_code, 200)
        res = {x["username"]: x for x in r.json()["results"]}
        self.assertEqual(r.json()["created"], 2)
        self.assertGreaterEqual(len(res["kim.minsu"]["password"]), 8)
        self.assertIn("error", res["amy"]); self.assertIn("error", res["bad name"]); self.assertIn("error", res["park.hana"])
        kim = TestClient(self.app); kim.headers["Origin"] = "http://testserver"
        login = kim.post("/api/login", json={"username": "kim.minsu", "password": res["kim.minsu"]["password"]})
        kim.headers["X-CSRF-Token"] = login.json()["csrf"]
        self.assertTrue(kim.get("/api/session").json()["must_change"])
        self.assertEqual(kim.get("/api/changes").status_code, 403)
        self.assertEqual(kim.post("/api/account/password", json={"current": res["kim.minsu"]["password"], "new": res["kim.minsu"]["password"]}).status_code, 409)
        self.assertEqual(kim.post("/api/account/password", json={"current": res["kim.minsu"]["password"], "new": "kim-own-pass"}).status_code, 200)
        self.assertFalse(kim.get("/api/session").json()["must_change"])
        self.assertEqual(kim.get("/api/chat/people").json()["groups"][0]["name"], "디자인팀")
        users = {u["username"]: u for u in boss.get("/api/admin/users").json()}
        self.assertIsNotNone(users["kim.minsu"]["last_login"]); self.assertTrue(users["lee.jiwon"]["must_change"])
        self.assertEqual(boss.post("/api/admin/users/bulk", json={"text": "\n".join(f"u{i}" for i in range(201))}).status_code, 413)
        kim.close()

    def test_backup_v2_includes_group_and_main_chat_not_dm(self):
        amy, boss = self.client("amy"), self.client("boss")
        pid = amy.post("/api/projects", json={"name": "P"}).json()["id"]
        amy.post(f"/api/projects/{pid}/notes", json={"body": "n"})
        amy.post("/api/chat/main", json={"body": "public"})
        amy.post(f"/api/chat/dm/{self.uid('ben')}", json={"body": "private"})
        boss.post(f"/api/projects/{pid}/archive")
        storage = Storage(self.settings)
        payload = json.loads(backup(self.app.state.engine, storage))
        self.assertEqual(payload["version"], 4)
        self.assertEqual([m["body"] for m in payload["tables"]["chat_messages"]], ["public"])
        self.assertEqual(payload["tables"]["chat_messages"][0]["sender_id"], self.uid("amy"))
        self.assertEqual(len(payload["tables"]["project_archives"]), 1)
        with tempfile.TemporaryDirectory() as other:
            target = create_app(Settings(database_url=f"sqlite:///{other}/r.db", data_dir=Path(other), origin="http://testserver", secure_cookies=False))
            counts = restore(target.state.engine, Storage(target.state.settings), json.dumps(payload).encode())
            self.assertEqual(counts["chat_messages"], 1); self.assertEqual(counts["work_notes"], 1)
            target.state.engine.dispose()

    def test_orca_link_modes(self):
        boss = self.client("boss")
        pid = boss.post("/api/projects", json={"name": "club"}).json()["id"]
        self.assertEqual(boss.post("/api/admin/orca-links", json={"project_id": pid, "mode": "new"}).status_code, 422)
        r = boss.post("/api/admin/orca-links", json={"project_id": pid, "mode": "new", "folder": "club-site"})
        self.assertEqual(r.status_code, 201); self.assertEqual(r.json()["repository_url"], "(new)")
        pid2 = boss.post("/api/projects", json={"name": "other"}).json()["id"]
        self.assertEqual(boss.post("/api/admin/orca-links", json={"project_id": pid2, "mode": "existing", "folder": "../x"}).status_code, 422)
        self.assertEqual(boss.post("/api/admin/orca-links", json={"project_id": pid2, "mode": "bogus", "folder": "x"}).status_code, 422)
        (Path(self.tmp.name) / "orca-folders.json").write_text(json.dumps({"updated": "t", "folders": [{"name": "kosmos-demo", "git": True}, {"name": "../bad"}]}))
        self.assertEqual([f["name"] for f in boss.get("/api/admin/orca").json()["server_folders"]["folders"]], ["kosmos-demo"])

    def test_worker_new_folder_mode(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("w", Path(__file__).resolve().parents[1] / "deploy" / "orca-link-worker.py")
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        boss = self.client("boss")
        pid = boss.post("/api/projects", json={"name": "club"}).json()["id"]
        boss.post("/api/admin/orca-links", json={"project_id": pid, "mode": "new", "folder": "club-site"})
        worker.PROJECTS = Path(self.tmp.name) / "projects"; worker.PROJECTS.mkdir()
        calls = []
        with Session(self.app.state.engine) as db, mock.patch.object(worker, "as_orca", side_effect=lambda a, t: calls.append(a) or SimpleNamespace(returncode=0, stdout="", stderr="")):
            detail = worker.process(db, db.get(OrcaLinkRequest, 1)); db.commit()
        self.assertEqual([c[0] for c in calls], ["mkdir", "git", "orca-ide"])
        self.assertIn("빈 프로젝트", detail)
        p = boss.get("/api/projects").json()[0]
        self.assertTrue(p["orca_available"]); self.assertEqual(p["repository_url"], "")


if __name__ == "__main__":
    unittest.main()
