import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import OrcaProject
from app.security import create_user

PW = "A-team-test-password-93"


class ExtrasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        for name, role in [("boss", "admin"), ("amy", "member"), ("ben", "member"), ("gus", "viewer")]:
            create_user(self.app.state.engine, name, PW, role)
        self.clients = {}

    def client(self, name):
        if name not in self.clients:
            c = TestClient(self.app); c.headers["Origin"] = "http://testserver"
            r = c.post("/api/login", json={"username": name, "password": PW}); c.headers["X-CSRF-Token"] = r.json()["csrf"]
            self.clients[name] = c
        return self.clients[name]

    def uid(self, name):
        return next(u["id"] for u in self.client("boss").get("/api/admin/users").json() if u["username"] == name)

    def tearDown(self):
        for c in self.clients.values():
            c.close()
        self.app.state.engine.dispose(); self.tmp.cleanup()

    def upload(self, who, pid, name="a.txt"):
        return self.client(who).post(f"/api/projects/{pid}/attachments", files={"file": (name, b"hello", "text/plain")})

    def test_attachment_delete_permissions(self):
        amy, ben, boss = self.client("amy"), self.client("ben"), self.client("boss")
        pid = amy.post("/api/projects", json={"name": "P"}).json()["id"]
        fid = self.upload("amy", pid).json()["id"]
        self.assertEqual(amy.get(f"/api/projects/{pid}/attachments").json()[0]["uploaded_by"], "amy")
        self.assertEqual(ben.delete(f"/api/attachments/{fid}").status_code, 403)
        self.assertEqual(amy.delete(f"/api/attachments/{fid}").status_code, 200)
        self.assertEqual(amy.get(f"/api/attachments/{fid}").status_code, 404)
        fid2 = self.upload("ben", pid).json()["id"]
        self.assertEqual(boss.delete(f"/api/attachments/{fid2}").status_code, 200)
        self.assertEqual(amy.get(f"/api/projects/{pid}/attachments").json(), [])
        self.assertEqual(self.client("gus").delete(f"/api/attachments/{fid2}").status_code, 403)  # viewer write blocked

    def test_chat_edit_delete(self):
        amy, ben, boss = self.client("amy"), self.client("ben"), self.client("boss")
        mid = amy.post("/api/chat/main", json={"body": "오타 있음"}).json()["id"]
        self.assertEqual(ben.patch(f"/api/chat/messages/{mid}", json={"body": "x"}).status_code, 403)
        self.assertEqual(boss.patch(f"/api/chat/messages/{mid}", json={"body": "x"}).status_code, 403)  # admins delete, not rewrite
        before = ben.get("/api/changes").json()["chat"]
        self.assertEqual(amy.patch(f"/api/chat/messages/{mid}", json={"body": "고친 메시지"}).status_code, 200)
        self.assertNotEqual(before, ben.get("/api/changes").json()["chat"])
        m = ben.get("/api/chat/main").json()[0]
        self.assertEqual((m["body"], bool(m["edited"]), m["deleted"]), ("고친 메시지", True, False))
        self.assertEqual(ben.delete(f"/api/chat/messages/{mid}").status_code, 403)
        self.assertEqual(boss.delete(f"/api/chat/messages/{mid}").status_code, 200)
        m = ben.get("/api/chat/main").json()[0]
        self.assertEqual((m["body"], m["deleted"]), ("", True))
        self.assertEqual(amy.delete(f"/api/chat/messages/{mid}").status_code, 409)
        self.assertEqual(amy.patch(f"/api/chat/messages/{mid}", json={"body": "다시"}).status_code, 409)
        self.assertEqual(amy.delete("/api/chat/messages/9999").status_code, 404)
        self.assertIn("deleted chat message", boss.get("/api/admin/audit?kind=content").json()[0]["summary"])

    def test_project_access_by_group(self):
        boss, amy, ben = self.client("boss"), self.client("amy"), self.client("ben")
        pid = boss.post("/api/projects", json={"name": "디자인 비공개"}).json()["id"]
        open_pid = boss.post("/api/projects", json={"name": "전체 공개"}).json()["id"]
        gid = boss.post("/api/admin/groups", json={"name": "디자인팀"}).json()["id"]
        boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy")]})
        nid = boss.post(f"/api/projects/{pid}/notes", json={"body": "비밀 메모"}).json()["id"]
        fid = self.upload("boss", pid).json()["id"]
        with Session(self.app.state.engine) as db:
            db.add(OrcaProject(project_id=pid, label="d", repository_url="")); db.commit()
        self.assertEqual(boss.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [9999]}).status_code, 404)
        self.assertEqual(amy.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [gid]}).status_code, 403)
        self.assertEqual(boss.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [gid]}).status_code, 200)
        # ben (not in group) sees nothing of the restricted project
        self.assertEqual([p["id"] for p in ben.get("/api/projects").json()], [open_pid])
        self.assertEqual(ben.get("/api/notes").json(), [])
        self.assertEqual(ben.get(f"/api/projects/{pid}/attachments").status_code, 404)
        self.assertEqual(ben.get(f"/api/attachments/{fid}").status_code, 404)
        self.assertEqual(ben.post(f"/api/projects/{pid}/notes", json={"body": "x"}).status_code, 404)
        self.assertEqual(self.upload("ben", pid).status_code, 404)
        self.assertEqual(ben.post(f"/api/projects/{pid}/orca").status_code, 404)
        self.assertEqual(ben.patch(f"/api/notes/{nid}", json={"body": "x"}).status_code, 404)
        # amy (in group) and boss (admin) see it
        self.assertIn(pid, [p["id"] for p in amy.get("/api/projects").json()])
        self.assertEqual(amy.get("/api/notes").json()[0]["body"], "비밀 메모")
        self.assertEqual(amy.get(f"/api/attachments/{fid}").status_code, 200)
        self.assertEqual(next(p for p in boss.get("/api/projects").json() if p["id"] == pid)["access_groups"], ["디자인팀"])
        # clearing access or deleting the group makes it visible again
        boss.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [gid]})
        self.assertEqual(boss.delete(f"/api/admin/groups/{gid}").status_code, 200)
        self.assertIn(pid, [p["id"] for p in ben.get("/api/projects").json()])

    def test_audit_log_admin_only_and_events_filtered(self):
        boss, amy = self.client("boss"), self.client("amy")
        boss.post("/api/admin/users", json={"username": "newbie", "password": "newbie-pass1", "role": "member"})
        self.assertEqual(amy.get("/api/admin/audit").status_code, 403)
        rows = boss.get("/api/admin/audit?q=newbie").json()
        self.assertTrue(rows and all("newbie" in r["summary"] for r in rows))
        self.assertEqual(boss.get("/api/admin/audit?kind=monitor").json(), [])  # not an audit kind
        self.assertFalse(any(e["kind"] == "account-access" for e in amy.get("/api/events").json()))
        self.assertTrue(any(e["kind"] == "account-access" for e in boss.get("/api/events").json()))

    def test_long_poll_wakes_on_any_write(self):
        import threading, time
        amy, ben = self.client("amy"), self.client("ben")
        v0 = ben.get("/api/wait?v=-1").json()["v"]           # returns at once with the current version
        self.assertEqual(TestClient(self.app).get("/api/wait?v=-1").status_code, 401)
        result = {}
        def waiter():
            t = time.monotonic(); result["v"] = ben.get(f"/api/wait?v={v0}").json()["v"]; result["s"] = time.monotonic() - t
        th = threading.Thread(target=waiter); th.start(); time.sleep(0.5)
        self.assertEqual(amy.post("/api/chat/main", json={"body": "지금 바로"}).status_code, 201)
        th.join(10)
        self.assertGreater(result["v"], v0)
        self.assertLess(result["s"], 3)                          # woke up well before the 25 s timeout
        before = ben.get("/api/wait?v=-1").json()["v"]
        amy.post("/api/chat/main", json={"body": "   "})           # failed write (422) does not wake anyone
        self.assertEqual(ben.get("/api/wait?v=-1").json()["v"], before)

    def test_delete_user_with_edited_dm(self):
        boss, amy = self.client("boss"), self.client("amy")
        mid = amy.post(f"/api/chat/dm/{self.uid('ben')}", json={"body": "hi"}).json()["id"]
        amy.patch(f"/api/chat/messages/{mid}", json={"body": "hello"})
        self.assertEqual(boss.delete(f"/api/admin/users/{self.uid('amy')}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
