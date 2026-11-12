"""Regressions from the main security/operations review; isolated databases only."""

import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
import test_suite as fixture

PW = fixture.PW
from app.models import (
    Base,
    ChatMessage,
    Task,
    TeamGroup,
    GroupMember,
    ProjectAccess,
    User,
    LoginSession,
)
from app.config import Settings
from app.ops import backup, restore
from app.storage import Storage
from app.security import token_hash, totp_code


class ReviewTests(unittest.TestCase):
    setUp, tearDown, client, uid = (
        fixture.SuiteTests.setUp,
        fixture.SuiteTests.tearDown,
        fixture.SuiteTests.client,
        fixture.SuiteTests.uid,
    )

    def restricted_project(self):
        boss = self.client("boss")
        pid = boss.post("/api/projects", json={"name": "Private"}).json()["id"]
        gid = boss.post("/api/admin/groups", json={"name": "Private group"}).json()[
            "id"
        ]
        boss.put(
            f"/api/admin/groups/{gid}/members", json={"user_ids": [self.uid("amy")]}
        )
        boss.put(f"/api/admin/projects/{pid}/access", json={"group_ids": [gid]})
        return pid, gid

    def test_deleting_last_group_never_publishes_project(self):
        pid, gid = self.restricted_project()
        ben = self.client("ben")
        self.assertEqual(ben.get(f"/api/projects/{pid}/attachments").status_code, 404)
        self.assertEqual(
            self.client("boss").delete(f"/api/admin/groups/{gid}").status_code, 200
        )
        self.assertEqual(ben.get(f"/api/projects/{pid}/attachments").status_code, 404)

    def test_deleted_chat_file_cannot_be_downloaded(self):
        amy, ben = self.client("amy"), self.client("ben")
        mid = amy.post(
            "/api/chat/main/0/files",
            files={"file": ("a.txt", b"private bytes", "text/plain")},
        ).json()["id"]
        self.assertEqual(ben.get(f"/api/chat/files/{mid}").status_code, 200)
        self.assertEqual(amy.delete(f"/api/chat/messages/{mid}").status_code, 200)
        self.assertEqual(ben.get(f"/api/chat/files/{mid}").status_code, 404)

    def test_totp_management_stops_guessing(self):
        amy = self.client("amy")
        secret = amy.post("/api/account/totp/setup", json={"password": PW}).json()[
            "secret"
        ]
        amy.post(
            "/api/account/totp/enable", json={"code": totp_code(secret), "password": PW}
        )
        statuses = [
            amy.post(
                "/api/account/totp/disable", json={"code": "abcdef", "password": PW}
            ).status_code
            for _ in range(8)
        ]
        self.assertIn(429, statuses)

    def test_incremental_chat_does_not_skip_backlog(self):
        amy = self.client("amy")
        uid = self.uid("amy")
        with Session(self.app.state.engine) as db:
            db.add_all(
                [
                    ChatMessage(
                        room="main",
                        sender_id=uid,
                        sender_name="amy",
                        body=str(i),
                        created="2026-11-12",
                    )
                    for i in range(202)
                ]
            )
            db.commit()
        first = amy.get("/api/chat/main?after=1").json()
        self.assertEqual([m["id"] for m in first], list(range(2, 202)))
        self.assertEqual(
            [m["id"] for m in amy.get("/api/chat/main?after=201").json()], [202]
        )

    def test_forced_password_denies_orca_session(self):
        from app.orca_gateway import live_session
        from app.teamwork import activity

        amy = self.client("amy")
        with Session(self.app.state.engine) as db:
            activity(db, self.uid("amy")).must_change = 1
            db.commit()
        self.assertFalse(
            live_session(self.app.state.engine, amy.cookies.get("kosmos_session"))
        )

    def test_backup_preserves_latest_business_data_and_visibility(self):
        pid, gid = self.restricted_project()
        amy = self.client("amy")
        amy.post("/api/tasks", json={"project_id": pid, "title": "Keep task"})
        mid = amy.post(
            f"/api/chat/group/{gid}/files",
            files={"file": ("a.txt", b"keep file", "text/plain")},
        ).json()["id"]
        archive = backup(self.app.state.engine, self.app.state.storage)
        payload = json.loads(archive)
        self.assertIn("tasks", payload["tables"])
        target = create_engine(f"sqlite:///{self.tmp.name}/restore.db")
        Base.metadata.create_all(target)
        with target.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        storage = Storage(Settings(data_dir=Path(self.tmp.name) / "restore"))
        try:
            restore(target, storage, archive)
            with Session(target) as db:
                self.assertEqual(db.scalar(select(Task)).title, "Keep task")
                self.assertIsNotNone(db.get(ProjectAccess, (pid, gid)))
                from app.extras import can_see_project

                self.assertFalse(
                    can_see_project(db, {"username": "ben", "role": "member"}, pid)
                )
                self.assertTrue(
                    can_see_project(db, {"username": "amy", "role": "member"}, pid)
                )
                from app.models import ChatAttachment

                f = db.get(ChatAttachment, mid)
                self.assertEqual(storage.get(f.key), b"keep file")
                self.assertFalse(list(db.scalars(select(LoginSession))))
        finally:
            target.dispose()

    def test_request_id_and_safe_diagnostics(self):
        amy = self.client("amy")
        r = amy.get("/api/session")
        self.assertTrue(r.headers.get("x-request-id"))
        self.assertEqual(amy.get("/api/admin/diagnostics").status_code, 403)
        r = self.client("boss").get("/api/admin/diagnostics")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(PW, r.text)
        self.assertNotIn("sqlite://", r.text)

    def test_notification_preferences_are_per_user(self):
        amy, ben = self.client("amy"), self.client("ben")
        r = amy.put(
            "/api/account/preferences", json={"notify": "mentions", "sound": False}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            amy.get("/api/account/preferences").json()["notify"], "mentions"
        )
        self.assertEqual(ben.get("/api/account/preferences").json()["notify"], "all")

    def test_mentions_only_reports_unread_mentions_from_all_my_rooms(self):
        amy, ben = self.client("amy"), self.client("ben")
        amy.post("/api/chat/main", json={"body": "hello @ben"})
        amy.post("/api/chat/main", json={"body": "ordinary text"})
        amy.post(f'/api/chat/dm/{self.uid("ben")}', json={"body": "DM @ben"})
        self.assertEqual(ben.get("/api/chat/people").json().get("mention_unread"), 2)

    def test_storage_quota_includes_legacy_files_and_stays_after_recreation(self):
        from app.models import Attachment
        from app.main import create_app

        amy = self.client("amy")
        pid = amy.post("/api/projects", json={"name": "Old files"}).json()["id"]
        with Session(self.app.state.engine) as db:
            db.add(
                Attachment(
                    project_id=pid,
                    key="attachments/" + "c" * 32,
                    name="old.txt",
                    size=1024 * 1024,
                    media_type="text/plain",
                )
            )
            db.commit()
        app = create_app(self.app.state.settings)
        try:
            with patch.dict("os.environ", {"UPLOAD_TOTAL_MIB": "1"}):
                from fastapi.testclient import TestClient

                with TestClient(app) as client:
                    client.headers["Origin"] = "http://testserver"
                    login = client.post(
                        "/api/login", json={"username": "amy", "password": PW}
                    )
                    client.headers["X-CSRF-Token"] = login.json()["csrf"]
                    self.assertEqual(
                        client.post(
                            f"/api/projects/{pid}/attachments",
                            files={"file": ("a.txt", b"x", "text/plain")},
                        ).status_code,
                        413,
                    )
        finally:
            app.state.engine.dispose()

    def test_dashboard_change_inbox_survives_logout_and_hides_private_projects(self):
        pid, gid = self.restricted_project()
        amy, ben = self.client("amy"), self.client("ben")
        amy.post(f"/api/projects/{pid}/notes", json={"body": "Do not leak body"})
        own = amy.get("/api/notices")
        self.assertEqual(own.status_code, 200)
        self.assertTrue(any(n.get("project_id") == pid for n in own.json()["items"]))
        self.assertFalse(
            any(
                n.get("project_id") == pid
                for n in ben.get("/api/notices").json()["items"]
            )
        )
        self.assertNotIn("Do not leak body", ben.get("/api/notices").text)
        boss = self.client("boss")
        self.assertEqual(
            boss.post(
                "/api/admin/notices",
                json={
                    "title": "Deployment complete",
                    "body": "Use the updated dashboard.",
                },
            ).status_code,
            201,
        )
        self.assertGreater(ben.get("/api/notices").json()["unread"], 0)
        last = ben.get("/api/notices").json()["items"][0]["id"]
        self.assertEqual(
            ben.post("/api/notices/read", json={"last_id": last}).status_code, 200
        )
        self.assertEqual(ben.get("/api/notices").json()["unread"], 0)
        ben.post("/api/logout")
        self.clients.pop("ben").close()
        self.assertEqual(self.client("ben").get("/api/notices").json()["unread"], 0)
        self.assertEqual(
            amy.post(
                "/api/admin/notices", json={"title": "fake", "body": "fake"}
            ).status_code,
            403,
        )

    def test_opening_already_rendered_room_acknowledges_only_displayed_messages(self):
        amy, ben = self.client("amy"), self.client("ben")
        mid = amy.post("/api/chat/main", json={"body": "unread"}).json()["id"]
        ben.get("/api/chat/main?read=false")
        self.assertEqual(ben.get("/api/chat/people").json()["main_unread"], 1)
        self.assertEqual(
            ben.post(
                "/api/chat/read", json={"room": "main", "last_id": mid}
            ).status_code,
            200,
        )
        self.assertEqual(ben.get("/api/chat/people").json()["main_unread"], 0)

    def test_excluded_dm_attachments_do_not_exhaust_team_backup_budget(self):
        from app.models import ChatAttachment

        uid = self.uid("amy")
        peer = self.uid("ben")
        with Session(self.app.state.engine) as db:
            for i in range(10):
                m = ChatMessage(
                    room="dm",
                    sender_id=uid,
                    sender_name="amy",
                    recipient_id=peer,
                    body="",
                    created="2026-11-12",
                )
                db.add(m)
                db.flush()
                db.add(
                    ChatAttachment(
                        message_id=m.id,
                        key="attachments/" + f"{i:032x}",
                        name="dm.txt",
                        media_type="text/plain",
                        size=1536 * 1024,
                    )
                )
            db.commit()
        payload = json.loads(backup(self.app.state.engine, self.app.state.storage))
        self.assertEqual(payload["tables"]["chat_attachments"], [])
