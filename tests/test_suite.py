import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import create_user, totp_code

PW = "A-team-test-password-93"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        for name, role in [("boss", "admin"), ("amy", "member"), ("ben", "member"), ("gus", "viewer")]:
            create_user(self.app.state.engine, name, PW, role)
        self.clients = {}

    def client(self, name, otp=""):
        if name not in self.clients:
            c = TestClient(self.app); c.headers["Origin"] = "http://testserver"
            r = c.post("/api/login", json={"username": name, "password": PW, "otp": otp})
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

    def test_chat_files_and_access(self):
        amy, ben, gus = self.client("amy"), self.client("ben"), self.client("gus")
        r = amy.post("/api/chat/main/0/files", files={"file": ("pic.png", PNG, "image/png")}, data={"body": "사진"})
        self.assertEqual(r.status_code, 201)
        mid = r.json()["id"]
        m = ben.get("/api/chat/main").json()[-1]
        self.assertEqual((m["body"], m["file"]["name"], m["file"]["image"]), ("사진", "pic.png", True))
        img = ben.get(f"/api/chat/files/{mid}")
        self.assertEqual((img.status_code, img.headers["content-type"]), (200, "image/png"))
        self.assertTrue(img.headers["content-disposition"].startswith("inline"))
        self.assertEqual(amy.post("/api/chat/main/0/files", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code, 415)
        dm = amy.post(f"/api/chat/dm/{self.uid('ben')}/files", files={"file": ("a.txt", b"hi", "text/plain")}).json()["id"]
        self.assertEqual(ben.get(f"/api/chat/files/{dm}").status_code, 200)
        self.assertEqual(gus.get(f"/api/chat/files/{dm}").status_code, 404)   # not a participant
        self.assertEqual(amy.post("/api/chat/group/999/files", files={"file": ("a.txt", b"hi", "text/plain")}).status_code, 404)

    def test_reply_reactions_search_pin(self):
        amy, ben, boss, gus = self.client("amy"), self.client("ben"), self.client("boss"), self.client("gus")
        first = amy.post("/api/chat/main", json={"body": "회의 3시 @ben"}).json()["id"]
        reply = ben.post("/api/chat/main", json={"body": "네!", "reply_to": first}).json()["id"]
        m = amy.get("/api/chat/main").json()[-1]
        self.assertEqual((m["id"], m["reply_to"]["id"], m["reply_to"]["sender"]), (reply, first, "amy"))
        dm = amy.post(f"/api/chat/dm/{self.uid('ben')}", json={"body": "비밀"}).json()["id"]
        self.assertEqual(gus.post("/api/chat/main", json={"body": "x", "reply_to": dm}).status_code, 404)  # cross-room quote refused
        self.assertEqual(ben.post(f"/api/chat/messages/{first}/react", json={"emoji": "👍"}).json()["added"], True)
        self.assertEqual(amy.post(f"/api/chat/messages/{first}/react", json={"emoji": "👍"}).json()["added"], True)
        r = next(x for x in amy.get("/api/chat/main").json() if x["id"] == first)["reactions"]
        self.assertEqual((r[0]["emoji"], r[0]["count"], r[0]["mine"]), ("👍", 2, True))
        self.assertEqual(ben.post(f"/api/chat/messages/{first}/react", json={"emoji": "👍"}).json()["added"], False)  # toggle off
        self.assertEqual(ben.post(f"/api/chat/messages/{first}/react", json={"emoji": "💩"}).status_code, 422)
        self.assertEqual(gus.post(f"/api/chat/messages/{dm}/react", json={"emoji": "👍"}).status_code, 404)
        hits = gus.get("/api/chat/search?q=비밀").json()
        self.assertEqual(hits, [])                                   # others' 1:1 is not searchable
        self.assertEqual([h["room"] for h in ben.get("/api/chat/search?q=비밀").json()], [f"u{self.uid('amy')}"])
        self.assertEqual(ben.get("/api/chat/search?q=회의").json()[0]["room"], "main")
        self.assertEqual(amy.post("/api/chat/pin", json={"message_id": first}).status_code, 403)  # main: admin only
        self.assertEqual(boss.post("/api/chat/pin", json={"message_id": first}).status_code, 200)
        self.assertEqual(gus.get("/api/chat/pin?room=main").json()["pin"]["message_id"], first)
        self.assertEqual(amy.post("/api/chat/pin", json={"message_id": dm}).status_code, 200)       # dm: participants
        self.assertEqual(ben.get(f"/api/chat/pin?room=u{self.uid('amy')}").json()["pin"]["body"], "비밀")
        self.assertEqual(boss.delete(f"/api/chat/pin/{first}").status_code, 200)
        self.assertIsNone(amy.get("/api/chat/pin?room=main").json()["pin"])

    def test_tasks_kanban_and_due(self):
        amy, ben, boss, gus = self.client("amy"), self.client("ben"), self.client("boss"), self.client("gus")
        pid = amy.post("/api/projects", json={"name": "P"}).json()["id"]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        t = amy.post("/api/tasks", json={"project_id": pid, "title": "발표 준비", "assignee": "ben", "due": tomorrow}).json()
        self.assertEqual(t["status"], "todo")
        self.assertEqual(amy.post("/api/tasks", json={"project_id": pid, "title": "x", "assignee": "nobody"}).status_code, 404)
        self.assertEqual(gus.post("/api/tasks", json={"project_id": pid, "title": "x"}).status_code, 403)   # viewer
        self.assertEqual([x["title"] for x in ben.get("/api/tasks/due").json()], ["발표 준비"])
        self.assertEqual(amy.get("/api/tasks/due").json(), [])
        self.assertEqual(ben.patch(f"/api/tasks/{t['id']}", json={"status": "doing"}).json()["status"], "doing")
        self.assertEqual(ben.patch(f"/api/tasks/{t['id']}", json={"status": "later"}).status_code, 422)
        ben.patch(f"/api/tasks/{t['id']}", json={"status": "done"})
        self.assertEqual(ben.get("/api/tasks/due").json(), [])        # done tasks do not alert
        self.assertEqual(ben.delete(f"/api/tasks/{t['id']}").status_code, 403)
        # project access applies to tasks
        gid = boss.post("/api/admin/groups", json={"name": "G"}).json()["id"]
        boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy")]})
        boss.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [gid]})
        self.assertEqual(ben.get("/api/tasks").json(), [])
        self.assertEqual(ben.get(f"/api/tasks?project_id={pid}").status_code, 404)
        self.assertEqual(amy.delete(f"/api/tasks/{t['id']}").status_code, 200)

    def test_profile_and_photo(self):
        amy, ben = self.client("amy"), self.client("ben")
        self.assertEqual(amy.put("/api/account/profile", json={"display_name": "에이미", "team": "디자인팀"}).status_code, 200)
        self.assertEqual(ben.get("/api/profiles").json()["amy"]["display_name"], "에이미")
        self.assertEqual(amy.post("/api/account/photo", files={"file": ("me.png", PNG, "image/png")}).status_code, 200)
        self.assertEqual(amy.post("/api/account/photo", files={"file": ("me.png", b"not an image", "image/png")}).status_code, 415)
        self.assertTrue(ben.get("/api/profiles").json()["amy"]["photo"])
        self.assertEqual(ben.get("/api/profiles/amy/photo").status_code, 200)
        self.assertEqual(ben.get("/api/profiles/ben/photo").status_code, 404)
        self.assertEqual(self.client("gus").put("/api/account/profile", json={"display_name": "게스트"}).status_code, 200)  # viewers manage their own profile

    def test_totp_login_flow(self):
        boss = self.client("boss")
        secret = boss.post("/api/account/totp/setup", json={"password": PW}).json()["secret"]
        self.assertEqual(boss.post("/api/account/totp/enable", json={"code": "000000"}).status_code, 403)
        self.assertEqual(boss.post("/api/account/totp/enable", json={"code": totp_code(secret)}).status_code, 200)
        self.assertTrue(boss.get("/api/account/totp").json()["enabled"])
        fresh = TestClient(self.app); fresh.headers["Origin"] = "http://testserver"
        r = fresh.post("/api/login", json={"username": "boss", "password": PW})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "OTP required"))
        self.assertEqual(fresh.post("/api/login", json={"username": "boss", "password": PW, "otp": "123456"}).json()["detail"], "Invalid OTP")
        self.assertEqual(fresh.post("/api/login", json={"username": "boss", "password": "wrong", "otp": totp_code(secret)}).json()["detail"], "Invalid credentials")
        self.assertEqual(fresh.post("/api/login", json={"username": "boss", "password": PW, "otp": totp_code(secret)}).status_code, 200)
        users = {u["username"]: u for u in fresh.get("/api/admin/users").json()}
        self.assertTrue(users["boss"]["totp"])
        fresh.close()

    def test_admin_resets_member_totp(self):
        amy = self.client("amy")
        secret = amy.post("/api/account/totp/setup", json={"password": PW}).json()["secret"]
        amy.post("/api/account/totp/enable", json={"code": totp_code(secret)})
        self.clients.pop("amy").close()
        boss = self.client("boss")
        self.assertEqual(boss.request("DELETE",f"/api/admin/users/{self.uid('amy')}/totp",json={"password":PW}).status_code, 200)
        self.assertEqual(self.client("amy").get("/api/account/totp").json()["enabled"], False)

    def test_idle_session_logs_out(self):
        amy = self.client("amy")
        self.assertEqual(amy.get("/api/session").status_code, 200)
        later = time.time() + 31 * 60
        with mock.patch("app.main.time.time", return_value=later):
            r = amy.get("/api/projects")
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "Session idle"))
        self.assertEqual(amy.get("/api/session").status_code, 401)

    def test_background_polling_does_not_keep_session_alive(self):
        amy = self.client("amy")
        amy.get("/api/session")
        start = time.time()
        with mock.patch("app.main.time.time", return_value=start + 20 * 60):
            self.assertEqual(amy.get("/api/changes").status_code, 200)   # background: does not refresh
        with mock.patch("app.main.time.time", return_value=start + 35 * 60):
            self.assertEqual(amy.get("/api/projects").status_code, 401)

    def test_delete_user_and_group_with_suite_data(self):
        amy, boss = self.client("amy"), self.client("boss")
        gid = boss.post("/api/admin/groups", json={"name": "G"}).json()["id"]
        boss.put(f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy"), self.uid("boss")]})
        g = amy.post(f"/api/chat/group/{gid}", json={"body": "그룹"}).json()["id"]
        amy.post(f"/api/chat/messages/{g}/react", json={"emoji": "👍"})
        amy.post("/api/chat/pin", json={"message_id": g})
        d = amy.post(f"/api/chat/dm/{self.uid('ben')}/files", files={"file": ("a.txt", b"hi", "text/plain")}).json()["id"]
        amy.post(f"/api/chat/messages/{d}/react", json={"emoji": "❤️"})
        amy.put("/api/account/profile", json={"display_name": "A"})
        self.assertEqual(boss.delete(f"/api/admin/groups/{gid}").status_code, 200)
        self.assertEqual(boss.delete(f"/api/admin/users/{self.uid('amy')}").status_code, 200)
        self.assertNotIn("amy", boss.get("/api/profiles").json())


if __name__ == "__main__":
    unittest.main()
