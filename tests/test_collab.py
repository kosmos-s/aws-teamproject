import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.security import create_user

PW = "A-team-test-password-93"


class CollabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        for name, role in [("boss", "admin"), ("amy", "member"), ("ben", "member"), ("gus", "viewer")]:
            create_user(self.app.state.engine, name, PW, role)
        self.clients = {}

    def client(self, name):
        if name not in self.clients:
            c = TestClient(self.app); c.headers["Origin"] = "http://testserver"
            r = c.post("/api/login", json={"username": name, "password": PW})
            self.assertEqual(r.status_code, 200)
            c.headers["X-CSRF-Token"] = r.json()["csrf"]
            self.clients[name] = c
        return self.clients[name]

    def uid(self, name):
        return next(u["id"] for u in self.client("boss").get("/api/admin/users").json() if u["username"] == name)

    def tearDown(self):
        for c in self.clients.values():
            c.close()
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_changes_fingerprint_moves_when_someone_writes(self):
        amy, ben = self.client("amy"), self.client("ben")
        before = ben.get("/api/changes").json()
        pid = amy.post("/api/projects", json={"name": "P"}).json()["id"]
        mid = ben.get("/api/changes").json()
        self.assertNotEqual(before["board"], mid["board"])
        amy.post(f"/api/projects/{pid}/notes", json={"body": "hello"})
        after = ben.get("/api/changes").json()
        self.assertNotEqual(mid["board"], after["board"])
        amy.post("/api/chat/main", json={"body": "hi"})
        self.assertNotEqual(after["chat"], ben.get("/api/changes").json()["chat"])
        self.assertEqual(TestClient(self.app).get("/api/changes").status_code, 401)

    def test_main_room_and_unread(self):
        amy, ben = self.client("amy"), self.client("ben")
        self.assertEqual(amy.post("/api/chat/main", json={"body": "  안녕하세요  "}).status_code, 201)
        self.assertEqual(ben.get("/api/chat/people").json()["main_unread"], 1)
        msgs = ben.get("/api/chat/main").json()
        self.assertEqual([(m["sender"], m["body"], m["mine"]) for m in msgs], [("amy", "안녕하세요", False)])
        self.assertEqual(ben.get("/api/chat/people").json()["main_unread"], 0)
        self.assertEqual(ben.get(f"/api/chat/main?after={msgs[-1]['id']}").json(), [])
        self.assertTrue(amy.get("/api/chat/main").json()[0]["mine"])

    def test_dm_is_private_and_counts_unread(self):
        amy, ben, gus = self.client("amy"), self.client("ben"), self.client("gus")
        self.assertEqual(amy.post(f"/api/chat/dm/{self.uid('ben')}", json={"body": "secret"}).status_code, 201)
        ben_people = {p["username"]: p for p in ben.get("/api/chat/people").json()["people"]}
        self.assertEqual(ben_people["amy"]["unread"], 1)
        self.assertEqual([m["body"] for m in ben.get(f"/api/chat/dm/{self.uid('amy')}").json()], ["secret"])
        self.assertEqual({p["username"]: p for p in ben.get("/api/chat/people").json()["people"]}["amy"]["unread"], 0)
        self.assertEqual(gus.get(f"/api/chat/dm/{self.uid('amy')}").json(), [])
        self.assertEqual(gus.get("/api/chat/main").json(), [])

    def test_viewer_can_chat_but_not_write_projects(self):
        gus = self.client("gus")
        self.assertEqual(gus.post("/api/chat/main", json={"body": "guest here"}).status_code, 201)
        self.assertEqual(gus.post(f"/api/chat/dm/{self.uid('amy')}", json={"body": "hi"}).status_code, 201)
        self.assertEqual(gus.post("/api/projects", json={"name": "no"}).status_code, 403)

    def test_chat_input_and_target_validation(self):
        amy = self.client("amy")
        self.assertEqual(amy.post("/api/chat/main", json={"body": "   "}).status_code, 422)
        self.assertEqual(amy.post("/api/chat/main", json={"body": "x" * 2001}).status_code, 422)
        self.assertEqual(amy.post(f"/api/chat/dm/{self.uid('amy')}", json={"body": "me"}).status_code, 404)
        self.assertEqual(amy.post("/api/chat/dm/9999", json={"body": "x"}).status_code, 404)
        self.assertEqual(amy.get("/api/chat/main?after=-1").status_code, 422)
        no_csrf = TestClient(self.app); no_csrf.headers["Origin"] = "http://testserver"
        no_csrf.cookies = amy.cookies
        self.assertEqual(no_csrf.post("/api/chat/main", json={"body": "x"}).status_code, 403)
        no_csrf.close()

    def test_chat_flood_protection(self):
        from unittest import mock
        import app.antispam as spam
        amy, ben = self.client("amy"), self.client("ben")
        codes = [amy.post("/api/chat/main", json={"body": f"m{i}"}).status_code for i in range(9)]
        self.assertEqual(codes[:8], [201] * 8)                 # 8 per 5 s burst
        r = amy.post("/api/chat/main", json={"body": "one more"})
        self.assertEqual((r.status_code, r.json()["detail"]), (429, "Too many messages"))
        self.assertTrue(1 <= int(r.headers["Retry-After"]) <= 6)
        self.assertEqual(ben.post("/api/chat/main", json={"body": "다른 사람은 영향 없음"}).status_code, 201)
        # same text a 3rd time within 30 s (outside the burst window)
        later = spam.time.time() + 6
        with mock.patch("app.antispam.time.time", return_value=later):
            self.assertEqual(ben.post("/api/chat/main", json={"body": "도배"}).status_code, 201)
            self.assertEqual(ben.post("/api/chat/main", json={"body": "  도배 "}).status_code, 201)
            dup = ben.post("/api/chat/main", json={"body": "도배"})
            self.assertEqual((dup.status_code, dup.json()["detail"]), (429, "Duplicate message"))
        # files count too
        with mock.patch("app.antispam.time.time", return_value=later):
            for i in range(6):  # 2 texts above + 6 files = 8 in the burst window
                ben.post("/api/chat/main/0/files", files={"file": (f"f{i}.txt", b"x", "text/plain")})
            self.assertEqual(ben.post("/api/chat/main/0/files", files={"file": ("z.txt", b"x", "text/plain")}).status_code, 429)

    def test_blocked_user_hidden_and_cannot_receive_dm(self):
        boss, amy = self.client("boss"), self.client("amy")
        boss.patch(f"/api/admin/users/{self.uid('ben')}", json={"active": False, "role": "member"})
        self.assertNotIn("ben", [p["username"] for p in amy.get("/api/chat/people").json()["people"]])
        self.assertEqual(amy.post(f"/api/chat/dm/{self.uid('ben')}", json={"body": "x"}).status_code, 409)

    def test_deleting_user_keeps_main_history_drops_dms(self):
        boss, amy, ben = self.client("boss"), self.client("amy"), self.client("ben")
        amy.post("/api/chat/main", json={"body": "public"})
        ben_id = self.uid("ben")
        amy.post(f"/api/chat/dm/{ben_id}", json={"body": "private"})
        amy_id = self.uid("amy")
        self.assertEqual(boss.delete(f"/api/admin/users/{amy_id}").status_code, 200)
        main = ben.get("/api/chat/main").json()
        self.assertEqual([(m["sender"], m["body"]) for m in main], [("amy", "public")])
        self.assertEqual(ben.get("/api/chat/people").json()["people"][0]["username"] in {"boss", "gus"}, True)
        self.assertEqual(ben.get(f"/api/chat/dm/{amy_id}").status_code, 404)

    def test_admin_user_list_reports_online_sessions(self):
        self.client("amy")
        users = {u["username"]: u for u in self.client("boss").get("/api/admin/users").json()}
        self.assertEqual(users["amy"]["sessions"], 1)
        self.assertEqual(users["ben"]["sessions"], 0)


if __name__ == "__main__":
    unittest.main()
