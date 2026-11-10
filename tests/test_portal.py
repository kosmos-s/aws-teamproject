import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import create_user


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            database_url=f"sqlite:///{Path(self.temp.name) / 'portal.db'}",
            data_dir=Path(self.temp.name),
            origin="http://testserver",
            secure_cookies=False,
        )
        self.app = create_app(self.settings)
        create_user(self.app.state.engine, "owner", "A-long-test-password-93", "admin")
        self.client = TestClient(self.app)
        self.client.headers["Origin"] = "http://testserver"

    def tearDown(self):
        self.client.close()
        self.app.state.engine.dispose()
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/login", json={"username": "owner", "password": "A-long-test-password-93"})
        self.assertEqual(response.status_code, 200)
        self.client.headers["X-CSRF-Token"] = response.json()["csrf"]
        return response

    def test_login_requires_correct_password_and_protects_cookie(self):
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"username": "owner", "password": "wrong"}).status_code, 401)
        response = self.login()
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        self.assertNotIn("password", self.client.get("/api/session").text)

    def test_csrf_and_foreign_origin_cannot_write(self):
        self.login()
        self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/projects", json={"name": "Project"}).status_code, 403)
        self.login()
        self.client.headers["Origin"] = "https://attacker.invalid"
        self.assertEqual(self.client.post("/api/projects", json={"name": "Project"}).status_code, 403)

    def test_logout_revokes_the_old_session(self):
        self.login()
        cookie = self.client.cookies.get("kosmos_session")
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.client.cookies.set("kosmos_session", cookie)
        self.assertEqual(self.client.get("/api/projects").status_code, 401)

    def test_projects_and_notes_survive_app_recreation(self):
        self.login()
        p = self.client.post("/api/projects", json={"name": "AWS demo", "description": "Team project"})
        self.assertEqual(p.status_code, 201)
        project_id = p.json()["id"]
        note = self.client.post(f"/api/projects/{project_id}/notes", json={"body": "한글 작업 메모"})
        self.assertEqual(note.status_code, 201)
        other = create_app(self.settings)
        with TestClient(other) as client:
            client.cookies.update(self.client.cookies)
            self.assertEqual(client.get("/api/projects").json()[0]["name"], "AWS demo")
            self.assertEqual(client.get("/api/notes").json()[0]["body"], "한글 작업 메모")
        other.state.engine.dispose()

    def test_blank_input_and_missing_project_are_rejected(self):
        self.login()
        self.assertEqual(self.client.post("/api/projects", json={"name": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/projects/999/notes", json={"body": "note"}).status_code, 404)

    def test_repeated_failed_login_is_throttled(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/login", json={"username": "owner", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"username": "owner", "password": "wrong"}).status_code, 429)

    def test_uploaded_file_requires_authentication_to_read(self):
        self.login()
        p = self.client.post("/api/projects", json={"name": "Files"}).json()
        response = self.client.post(f"/api/projects/{p['id']}/attachments", files={"file": ("readme.txt", b"AWS attachment", "text/plain")})
        self.assertEqual(response.status_code, 201)
        file_id = response.json()["id"]
        self.assertEqual(self.client.get(f"/api/attachments/{file_id}").content, b"AWS attachment")
        self.client.post("/api/logout")
        self.assertEqual(self.client.get(f"/api/attachments/{file_id}").status_code, 401)

    def test_oversized_upload_and_executable_type_are_rejected(self):
        self.login()
        p = self.client.post("/api/projects", json={"name": "Files"}).json()
        url = f"/api/projects/{p['id']}/attachments"
        self.assertEqual(self.client.post(url, files={"file": ("script.html", b"<script>bad()</script>", "text/html")}).status_code, 415)
        self.assertEqual(self.client.post(url, files={"file": ("large.txt", b"x" * (1024 * 1024 + 1), "text/plain")}).status_code, 413)

    def test_status_does_not_invent_a_successful_check(self):
        self.login()
        self.assertEqual(self.client.get("/api/status").json()["state"], "unknown")
        self.assertEqual(self.client.get("/api/events").json(), [])

    def test_slow_storage_does_not_block_health_requests(self):
        self.login()
        project = self.client.post("/api/projects", json={"name": "Slow storage"}).json()
        entered, release = threading.Event(), threading.Event()
        original = self.app.state.storage.put

        def slow_put(*args):
            entered.set()
            release.wait(5)
            return original(*args)

        self.app.state.storage.put = slow_put
        with TestClient(self.app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            client.cookies.update(self.client.cookies)
            client.headers.update(self.client.headers)
            upload = pool.submit(client.post, f"/api/projects/{project['id']}/attachments", files={"file": ("slow.txt", b"slow", "text/plain")})
            try:
                self.assertTrue(entered.wait(2))
                health = pool.submit(client.get, "/health")
                try:
                    self.assertEqual(health.result(timeout=1).status_code, 200)
                except TimeoutError:
                    self.fail("Slow storage blocked unrelated health request")
            finally:
                release.set()
                upload.result(timeout=5)


if __name__ == "__main__":
    unittest.main()
