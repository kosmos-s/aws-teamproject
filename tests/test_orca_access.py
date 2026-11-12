import base64
import json
import tempfile
import threading
import time
import asyncio
from contextlib import asynccontextmanager
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.server import serve
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.security import create_user


class OrcaAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(database_url=f"sqlite:///{self.tmp.name}/portal.db", data_dir=Path(self.tmp.name), origin="http://testserver", secure_cookies=False))
        create_user(self.app.state.engine, "tester", "A-manual-test-password-93")
        self.client = TestClient(self.app)
        self.client.headers["Origin"] = "http://testserver"

    def tearDown(self):
        self.client.close()
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def login(self, client=None):
        client = client or self.client
        response = client.post("/api/login", json={"username": "tester", "password": "A-manual-test-password-93"})
        client.headers["X-CSRF-Token"] = response.json()["csrf"]

    def test_authorization_requires_live_portal_session(self):
        self.assertEqual(self.client.get("/api/orca/authorize").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/orca/authorize").status_code, 204)
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/orca/authorize").status_code, 401)

    def test_webmin_authorization_is_admin_only(self):
        self.assertEqual(self.client.get("/api/admin/authorize").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/admin/authorize").status_code, 403)
        create_user(self.app.state.engine, "admin", "A-manual-admin-password-93", "admin")
        self.client.post("/api/login", json={"username": "admin", "password": "A-manual-admin-password-93"})
        self.assertEqual(self.client.get("/api/admin/authorize").status_code, 204)

    def test_launch_rejects_unmapped_project_and_requires_csrf(self):
        self.login()
        project = self.client.post("/api/projects", json={"name": "Not registered"}).json()
        self.assertEqual(self.client.post(f"/api/projects/{project['id']}/orca").status_code, 409)
        self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post(f"/api/projects/{project['id']}/orca").status_code, 403)

    def test_launch_uses_fixed_mapping_and_fragment_without_leaking_into_project_list(self):
        from app.models import OrcaProject
        self.login()
        project = self.client.post("/api/projects", json={"name": "Registered"}).json()
        with Session(self.app.state.engine) as db:
            db.add(OrcaProject(project_id=project["id"], label="aws-teamproject", repository_url="https://github.com/kosmos-s/aws-teamproject"))
            db.commit()
        with patch("app.orca_gateway.obtain_pairing", return_value={"v": 1, "deviceToken": "test-offer", "publicKeyB64": "public", "endpoint": "ws://127.0.0.1:6768"}):
            response = self.client.post(f"/api/projects/{project['id']}/orca")
        self.assertEqual(response.status_code, 200)
        url = response.json()["url"]
        self.assertTrue(url.startswith("/orca/web-index.html#pairing="))
        payload = url.split("=", 1)[1]
        offer = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        self.assertEqual(offer["endpoint"], "ws://testserver/orca/runtime")
        projects = self.client.get("/api/projects").json()
        self.assertTrue(projects[0]["orca_available"])
        self.assertNotIn("test-offer", json.dumps(projects))

    def test_websocket_rejects_anonymous_and_foreign_origin(self):
        with self.assertRaises(WebSocketDisconnect) as context:
            with self.client.websocket_connect("/orca/runtime", headers={"Origin": "http://testserver"}):
                pass
        self.assertEqual(context.exception.code, 1008)
        self.login()
        with self.assertRaises(WebSocketDisconnect) as context:
            with self.client.websocket_connect("/orca/runtime", headers={"Origin": "https://other.invalid"}):
                pass
        self.assertEqual(context.exception.code, 1008)

    def test_existing_websocket_closes_after_logout(self):
        def echo(socket):
            for message in socket:
                socket.send(message)
        with serve(echo, "127.0.0.1", 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.app.state.orca_upstream = f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
            with TestClient(self.app) as client:
                client.headers["Origin"] = "http://testserver"
                self.login(client)
                with client.websocket_connect("/orca/runtime", headers={"Origin": "http://testserver"}) as socket:
                    socket.send_bytes(b"opaque native E2EE frame")
                    self.assertEqual(socket.receive_bytes(), b"opaque native E2EE frame")
                    client.post("/api/logout")
                    with self.assertRaises(WebSocketDisconnect) as context:
                        socket.receive_bytes()
                    self.assertEqual(context.exception.code, 1008)
            server.shutdown()
            thread.join(timeout=3)

    def test_logout_closes_socket_during_slow_upstream_handshake(self):
        @asynccontextmanager
        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(4)
            yield None
        with patch("app.orca_gateway.connect", slow_connect), TestClient(self.app) as client:
            client.headers["Origin"] = "http://testserver"
            self.login(client)
            with client.websocket_connect("/orca/runtime", headers={"Origin": "http://testserver"}) as socket:
                start = time.monotonic()
                client.post("/api/logout")
                with self.assertRaises(WebSocketDisconnect) as context:
                    socket.receive_bytes()
                self.assertEqual(context.exception.code, 1008)
                self.assertLess(time.monotonic() - start, 2)
