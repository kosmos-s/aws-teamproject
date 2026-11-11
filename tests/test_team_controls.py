import tempfile
import unittest
import threading
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.security import create_user
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve


class TeamControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/p.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        create_user(self.app.state.engine, "owner", "A-team-test-password-93", "admin")
        create_user(self.app.state.engine, "member", "A-team-test-password-93")
        self.client = TestClient(self.app)
        self.client.headers["Origin"] = "http://testserver"
        self.login(self.client, "owner")

    def login(self, client, username):
        response = client.post("/api/login", json={"username": username, "password": "A-team-test-password-93"})
        self.assertEqual(response.status_code, 200)
        client.headers["X-CSRF-Token"] = response.json()["csrf"]

    def tearDown(self):
        self.client.close()
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def test_member_cannot_manage_accounts_or_read_cost_inventory(self):
        self.login(self.client, "member")
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/operations").status_code, 403)

    def test_disabling_member_revokes_session_and_blocks_login(self):
        member = TestClient(self.app)
        member.headers["Origin"] = "http://testserver"
        self.login(member, "member")
        users = self.client.get("/api/admin/users").json()
        target = next(u for u in users if u["username"] == "member")
        response = self.client.patch(f"/api/admin/users/{target['id']}", json={"active": False, "role": "member"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(member.get("/api/projects").status_code, 401)
        self.assertEqual(member.post("/api/login", json={"username": "member", "password": "A-team-test-password-93"}).status_code, 401)
        member.close()

    def test_admin_can_create_viewer_but_viewer_cannot_write_or_access_orca(self):
        response = self.client.post("/api/admin/users", json={"username": "guest", "password": "A-team-test-password-93", "role": "viewer"})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.text)
        self.login(self.client, "guest")
        # Admin-created accounts must replace the initial password before anything else.
        self.assertEqual(self.client.get("/api/projects").status_code, 403)
        self.assertTrue(self.client.get("/api/session").json()["must_change"])
        self.assertEqual(self.client.post("/api/account/password", json={"current": "A-team-test-password-93", "new": "guest-own-pass"}).status_code, 200)
        self.assertEqual(self.client.get("/api/projects").status_code, 200)
        self.assertEqual(self.client.post("/api/projects", json={"name": "Forbidden"}).status_code, 403)
        self.assertEqual(self.client.get("/api/orca/authorize").status_code, 403)
        self.assertEqual(self.client.post("/api/logout").status_code, 200)

    def member_client(self):
        member = TestClient(self.app)
        member.headers["Origin"] = "http://testserver"
        self.login(member, "member")
        return member

    def user_id(self, name):
        return next(u["id"] for u in self.client.get("/api/admin/users").json() if u["username"] == name)

    def test_admin_resets_password_and_revokes_sessions(self):
        member = self.member_client()
        response = self.client.put(f"/api/admin/users/{self.user_id('member')}/password", json={"password": "newpass1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sessions_revoked"], 1)
        self.assertEqual(member.get("/api/projects").status_code, 401)
        self.assertEqual(member.post("/api/login", json={"username": "member", "password": "A-team-test-password-93"}).status_code, 401)
        self.assertEqual(member.post("/api/login", json={"username": "member", "password": "newpass1"}).status_code, 200)
        self.assertNotIn("newpass1", response.text)
        member.close()

    def test_password_reset_refusals(self):
        self.assertEqual(self.client.put(f"/api/admin/users/{self.user_id('owner')}/password", json={"password": "longenough1"}).status_code, 409)
        self.assertEqual(self.client.put("/api/admin/users/9999/password", json={"password": "longenough1"}).status_code, 404)
        self.assertEqual(self.client.put(f"/api/admin/users/{self.user_id('member')}/password", json={"password": "short7!"}).status_code, 422)
        member = self.member_client()
        self.assertEqual(member.put(f"/api/admin/users/{self.user_id('owner')}/password", json={"password": "longenough1"}).status_code, 403)
        member.close()

    def test_user_changes_own_password_keeps_current_session(self):
        other = self.member_client()
        member = self.member_client()
        wrong = member.post("/api/account/password", json={"current": "nope", "new": "abcdefgh"})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(member.get("/api/session").status_code, 200)
        ok = member.post("/api/account/password", json={"current": "A-team-test-password-93", "new": "abcdefgh"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["other_sessions_revoked"], 1)
        self.assertEqual(member.get("/api/session").status_code, 200)
        self.assertEqual(other.get("/api/session").status_code, 401)
        self.assertEqual(other.post("/api/login", json={"username": "member", "password": "abcdefgh"}).status_code, 200)
        other.close(); member.close()

    def test_viewer_can_change_own_password(self):
        create_user(self.app.state.engine, "watcher", "A-team-test-password-93", "viewer")
        viewer = TestClient(self.app); viewer.headers["Origin"] = "http://testserver"
        self.login(viewer, "watcher")
        self.assertEqual(viewer.post("/api/account/password", json={"current": "A-team-test-password-93", "new": "viewer-pw-1"}).status_code, 200)
        self.assertEqual(viewer.post("/api/projects", json={"name": "x"}).status_code, 403)
        viewer.close()

    def test_admin_deletes_member_and_sessions(self):
        member = self.member_client()
        self.client.post("/api/projects", json={"name": "P"})
        pid = self.client.get("/api/projects").json()[0]["id"]
        self.assertEqual(member.post(f"/api/projects/{pid}/notes", json={"body": "keep me"}).status_code, 201)
        response = self.client.delete(f"/api/admin/users/{self.user_id('member')}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(member.get("/api/projects").status_code, 401)
        self.assertEqual(member.post("/api/login", json={"username": "member", "password": "A-team-test-password-93"}).status_code, 401)
        self.assertNotIn("member", [u["username"] for u in self.client.get("/api/admin/users").json()])
        self.assertEqual(self.client.get("/api/notes").json()[0]["author"], "member")
        recreated = self.client.post("/api/admin/users", json={"username": "member", "password": "recreate1", "role": "member"})
        self.assertEqual(recreated.status_code, 201)
        member.close()

    def test_delete_refusals(self):
        self.assertEqual(self.client.delete(f"/api/admin/users/{self.user_id('owner')}").status_code, 409)
        self.assertEqual(self.client.delete("/api/admin/users/9999").status_code, 404)
        create_user(self.app.state.engine, "boss2", "A-team-test-password-93", "admin")
        second = TestClient(self.app); second.headers["Origin"] = "http://testserver"
        self.login(second, "boss2")
        owner_id, member_id = self.user_id("owner"), self.user_id("member")
        self.assertEqual(second.delete(f"/api/admin/users/{owner_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)
        self.assertEqual(second.delete(f"/api/admin/users/{member_id}").status_code, 200)
        boss2_id = next(u["id"] for u in second.get("/api/admin/users").json() if u["username"] == "boss2")
        self.assertEqual(second.delete(f"/api/admin/users/{boss2_id}").status_code, 409)
        second.close()

    def test_password_needs_eight_characters(self):
        short = self.client.post("/api/admin/users", json={"username": "shorty", "password": "1234567", "role": "member"})
        self.assertEqual(short.status_code, 422)
        ok = self.client.post("/api/admin/users", json={"username": "eight", "password": "abcd1234", "role": "member"})
        self.assertEqual(ok.status_code, 201)
        empty = self.client.post("/api/admin/users", json={"username": "blank", "password": "", "role": "member"})
        self.assertEqual(empty.status_code, 422)
        self.assertNotIn("blank", [u["username"] for u in self.client.get("/api/admin/users").json()])

    def test_last_admin_cannot_lock_or_demote_self(self):
        user = next(u for u in self.client.get("/api/admin/users").json() if u["username"] == "owner")
        self.assertEqual(self.client.patch(f"/api/admin/users/{user['id']}", json={"active": False, "role": "viewer"}).status_code, 409)

    def test_operations_without_snapshot_is_unknown(self):
        response = self.client.get("/api/admin/operations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "unknown")

    def test_invalid_password_is_never_echoed_in_validation_response(self):
        response = self.client.post("/api/admin/users", json={"username": "bad", "password": "SENSITIVE", "role": "superuser"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("SENSITIVE", response.text)

    def test_account_block_closes_existing_member_websocket(self):
        def echo(socket):
            for item in socket:
                socket.send(item)
        target = next(u for u in self.client.get("/api/admin/users").json() if u["username"] == "member")
        with serve(echo, "127.0.0.1", 0) as upstream:
            thread = threading.Thread(target=upstream.serve_forever, daemon=True)
            thread.start()
            self.app.state.orca_upstream = f"ws://127.0.0.1:{upstream.socket.getsockname()[1]}"
            with TestClient(self.app) as member:
                member.headers["Origin"] = "http://testserver"
                self.login(member, "member")
                with member.websocket_connect("/orca/runtime", headers={"Origin": "http://testserver"}) as socket:
                    socket.send_bytes(b"native-frame")
                    self.assertEqual(socket.receive_bytes(), b"native-frame")
                    started = time.monotonic()
                    self.assertEqual(self.client.patch(f"/api/admin/users/{target['id']}", json={"active": False, "role": "member"}).status_code, 200)
                    with self.assertRaises(WebSocketDisconnect) as context:
                        socket.receive_bytes()
                    self.assertEqual(context.exception.code, 1008)
                    self.assertLess(time.monotonic() - started, 2)
            upstream.shutdown()
            thread.join(timeout=3)
