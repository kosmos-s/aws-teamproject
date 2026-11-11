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
        self.assertEqual(self.client.get("/api/projects").status_code, 200)
        self.assertEqual(self.client.post("/api/projects", json={"name": "Forbidden"}).status_code, 403)
        self.assertEqual(self.client.get("/api/orca/authorize").status_code, 403)
        self.assertEqual(self.client.post("/api/logout").status_code, 200)

    def test_last_admin_cannot_lock_or_demote_self(self):
        user = next(u for u in self.client.get("/api/admin/users").json() if u["username"] == "owner")
        self.assertEqual(self.client.patch(f"/api/admin/users/{user['id']}", json={"active": False, "role": "viewer"}).status_code, 409)

    def test_operations_without_snapshot_is_unknown(self):
        response = self.client.get("/api/admin/operations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "unknown")

    def test_invalid_password_is_never_echoed_in_validation_response(self):
        response = self.client.post("/api/admin/users", json={"username": "bad", "password": "SENSITIVE", "role": "member"})
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
