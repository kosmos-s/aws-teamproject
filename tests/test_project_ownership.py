import unittest
import test_suite as fixture
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Project, Note, OrcaProject, Attachment, ObjectDeletion


class OwnershipTests(unittest.TestCase):
    setUp, tearDown, client, uid = (
        fixture.SuiteTests.setUp,
        fixture.SuiteTests.tearDown,
        fixture.SuiteTests.client,
        fixture.SuiteTests.uid,
    )

    def project(self):
        return (
            self.client("amy")
            .post("/api/projects", json={"name": "Owner project"})
            .json()["id"]
        )

    def test_access_write_rechecks_owner_after_authentication_dependency(self):
        from app.models import ProjectOwner

        pid = self.project()
        amy = self.client("amy")
        route = next(
            r
            for r in self.app.routes
            if getattr(r, "path", "") == "/api/projects/{project_id}/access"
            and "PUT" in r.methods
        )
        dependency = route.dependant.dependencies[0].call

        def transferred_actor():
            with Session(self.app.state.engine) as db:
                db.get(ProjectOwner, pid).user_id = self.uid("ben")
                db.commit()
            return {"id": self.uid("amy"), "username": "amy", "role": "member"}

        self.app.dependency_overrides[dependency] = transferred_actor
        try:
            response = amy.put(
                f"/api/projects/{pid}/access",
                json={"restricted": False, "group_ids": []},
            )
            self.assertEqual(response.status_code, 403, response.text)
        finally:
            self.app.dependency_overrides.clear()

    def test_creator_manages_and_other_member_cannot(self):
        pid = self.project()
        amy, ben, boss = self.client("amy"), self.client("ben"), self.client("boss")
        p = next(p for p in amy.get("/api/projects").json() if p["id"] == pid)
        self.assertEqual(p.get("owner"), "amy")
        self.assertTrue(p.get("can_manage"))
        self.assertEqual(
            ben.patch(
                f"/api/projects/{pid}", json={"name": "hijack", "description": ""}
            ).status_code,
            403,
        )
        self.assertEqual(
            amy.patch(
                f"/api/projects/{pid}",
                json={"name": "Renamed", "description": "updated"},
            ).status_code,
            200,
        )
        self.assertEqual(
            amy.put(
                f"/api/projects/{pid}/access",
                json={"restricted": True, "group_ids": []},
            ).status_code,
            200,
        )
        self.assertIn(pid, [p["id"] for p in amy.get("/api/projects").json()])
        self.assertNotIn(pid, [p["id"] for p in ben.get("/api/projects").json()])
        self.assertEqual(amy.post(f"/api/projects/{pid}/archive").status_code, 200)
        self.assertEqual(amy.delete(f"/api/projects/{pid}/archive").status_code, 200)
        self.assertEqual(
            boss.patch(
                f"/api/projects/{pid}", json={"name": "Admin", "description": ""}
            ).status_code,
            200,
        )

    def test_transfer_and_owner_account_deletion_guard(self):
        pid = self.project()
        amy, ben, boss = self.client("amy"), self.client("ben"), self.client("boss")
        self.assertEqual(
            boss.delete(f'/api/admin/users/{self.uid("amy")}').status_code, 409
        )
        self.assertEqual(
            ben.put(
                f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")}
            ).status_code,
            403,
        )
        self.assertEqual(
            amy.put(
                f"/api/projects/{pid}/owner", json={"user_id": self.uid("gus")}
            ).status_code,
            422,
        )
        self.assertEqual(
            amy.put(
                f"/api/projects/{pid}/owner", json={"user_id": self.uid("ben")}
            ).status_code,
            200,
        )
        self.assertEqual(
            amy.patch(
                f"/api/projects/{pid}", json={"name": "old owner", "description": ""}
            ).status_code,
            403,
        )
        self.assertEqual(
            ben.patch(
                f"/api/projects/{pid}", json={"name": "new owner", "description": ""}
            ).status_code,
            200,
        )
        self.assertEqual(
            boss.delete(f'/api/admin/users/{self.uid("amy")}').status_code, 200
        )

    def test_legacy_project_only_admin_can_assign_owner(self):
        with Session(self.app.state.engine) as db:
            p = Project(name="Legacy", description="", created="2026-11-12")
            db.add(p)
            db.commit()
            pid = p.id
        self.assertEqual(
            self.client("amy")
            .put(f"/api/projects/{pid}/owner", json={"user_id": self.uid("amy")})
            .status_code,
            403,
        )
        self.assertEqual(
            self.client("boss")
            .put(f"/api/projects/{pid}/owner", json={"user_id": self.uid("amy")})
            .status_code,
            200,
        )

    def test_permanent_delete_admin_only_preserves_workspace(self):
        pid = self.project()
        amy = self.client("amy")
        boss = self.client("boss")
        amy.post(f"/api/projects/{pid}/notes", json={"body": "Remove note"})
        amy.post("/api/tasks", json={"project_id": pid, "title": "Remove task"})
        amy.post(
            f"/api/projects/{pid}/attachments",
            files={"file": ("a.txt", b"hello", "text/plain")},
        )
        with Session(self.app.state.engine) as db:
            db.add(
                OrcaProject(project_id=pid, label="preserve-folder", repository_url="")
            )
            db.commit()
        self.assertEqual(amy.delete(f"/api/projects/{pid}").status_code, 403)
        self.assertEqual(
            boss.request(
                "DELETE", f"/api/projects/{pid}", json={"confirmation": "Owner project"}
            ).status_code,
            200,
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(Project, pid))
            self.assertIsNone(db.scalar(select(Note)))
            self.assertIsNone(db.scalar(select(Attachment)))

    def test_github_create_is_atomic_and_url_is_optional(self):
        amy = self.client("amy")
        before = len(amy.get("/api/projects").json())
        self.assertEqual(
            amy.post(
                "/api/projects",
                json={"name": "Bad", "repository_url": "https://evil.example/a"},
            ).status_code,
            422,
        )
        self.assertEqual(len(amy.get("/api/projects").json()), before)
        r = amy.post(
            "/api/projects",
            json={"name": "GitHub", "repository_url": "https://github.com/a/team.git"},
        )
        self.assertEqual(r.status_code, 201)
        status = amy.get(f'/api/projects/{r.json()["id"]}/repository')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["repository_url"], "https://github.com/a/team")
        self.assertEqual(status.json()["jobs"][0]["kind"], "link")
        self.assertEqual(
            amy.get(f"/api/projects/{self.project()}/repository").json()["jobs"], []
        )

    def test_admin_permanent_delete_requires_matching_confirmation(self):
        pid = self.project()
        boss = self.client("boss")
        self.assertEqual(boss.delete(f"/api/projects/{pid}").status_code, 422)
        self.assertEqual(
            boss.request(
                "DELETE", f"/api/projects/{pid}", json={"confirmation": "wrong"}
            ).status_code,
            409,
        )
        self.assertIn(pid, [p["id"] for p in boss.get("/api/projects").json()])
