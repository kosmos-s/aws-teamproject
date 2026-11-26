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

    def test_isolated_launch_and_socket_require_the_same_project_access(self):
        from app.models import OrcaProject, Project, ProjectPolicy

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        registry = root / "orca-projects.json"
        registry.write_text('{"1": 18681, "2": 18682}', encoding="utf-8")
        app = create_app(Settings(database_url=f"sqlite:///{root / 'isolated.db'}",
                                  data_dir=root, origin="http://testserver",
                                  secure_cookies=False, orca_project_registry=registry))
        self.addCleanup(app.state.engine.dispose)
        create_user(app.state.engine, "tester", "A-manual-test-password-93")
        with Session(app.state.engine) as db:
            db.add_all([Project(id=1, name="Accessible", created="2026-11-21T00:00:00+00:00"),
                        Project(id=2, name="Private", created="2026-11-21T00:00:00+00:00")])
            db.flush()
            for pid in (1, 2):
                db.add(OrcaProject(project_id=pid, label=f"project-{pid}", repository_url=""))
            db.add(ProjectPolicy(project_id=2, restricted=1))
            db.commit()
        with TestClient(app) as client:
            client.headers["Origin"] = "http://testserver"
            self.login(client)
            with patch("app.orca_gateway.obtain_pairing", return_value={"deviceToken": "synthetic", "publicKeyB64": "public"}) as pair:
                result = client.post("/api/projects/1/orca")
                self.assertEqual(result.status_code, 200)
                payload = result.json()["url"].split("=", 1)[1]
                self.assertEqual(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["endpoint"],
                                 "ws://testserver/orca/runtime/1")
                pair.assert_called_once_with(Path("/run/kosmos-orca-projects/1/pair.sock"))
                self.assertEqual(client.post("/api/projects/2/orca").status_code, 404)
            for path in ("/orca/runtime", "/orca/runtime/2", "/orca/runtime/3"):
                with self.subTest(path=path), self.assertRaises(WebSocketDisconnect) as context:
                    with client.websocket_connect(path, headers={"Origin": "http://testserver"}):
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
