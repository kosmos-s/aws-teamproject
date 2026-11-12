import unittest
from concurrent.futures import ThreadPoolExecutor
import test_suite as fixture
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app.models import ChatRead, LoginSession, UserTotp, TotpVault, ObjectDeletion, User
from app.antispam import AntiSpam
from app.db_atomic import mark_read
from app.security import totp_code


class ConcurrencyTests(unittest.TestCase):
    setUp, tearDown, client, uid = (
        fixture.SuiteTests.setUp,
        fixture.SuiteTests.tearDown,
        fixture.SuiteTests.client,
        fixture.SuiteTests.uid,
    )

    def test_parallel_read_updates_never_regress_or_duplicate(self):
        uid = self.uid("amy")

        def update(value):
            with Session(self.app.state.engine) as db:
                mark_read(db, uid, "main", value)
                db.commit()

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(update, [20, 1, 90, 15, 30, 100, 99, 8] * 4))
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(ChatRead, (uid, "main")).last_id, 100)

    def test_parallel_login_leaves_exactly_one_active_session(self):
        def login(_):
            with TestClient(self.app) as c:
                return c.post(
                    "/api/login",
                    headers={"Origin": "http://testserver"},
                    json={"username": "amy", "password": fixture.PW},
                ).status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(login, range(6)))
        self.assertEqual(statuses, [200] * 6)
        with Session(self.app.state.engine) as db:
            uid = db.scalar(select(User.id).where(User.username == "amy"))
            self.assertEqual(
                db.scalar(
                    select(func.count(LoginSession.token_hash)).where(
                        LoginSession.user_id == uid
                    )
                ),
                1,
            )

    def test_parallel_spam_attempts_do_not_exceed_burst(self):
        spam = AntiSpam()

        def send(i):
            try:
                spam.check(1, f"message {i}")
                return True
            except HTTPException as e:
                if e.status_code != 429:
                    raise
                return False

        with ThreadPoolExecutor(max_workers=25) as pool:
            accepted = sum(pool.map(send, range(40)))
        self.assertEqual(accepted, 8)

    def test_totp_seed_is_encrypted_and_recovery_code_is_single_use(self):
        amy = self.client("amy")
        secret = amy.post(
            "/api/account/totp/setup", json={"password": fixture.PW}
        ).json()["secret"]
        codes = amy.post(
            "/api/account/totp/enable", json={"code": totp_code(secret)}
        ).json()["recovery_codes"]
        with Session(self.app.state.engine) as db:
            uid = db.scalar(select(User.id).where(User.username == "amy"))
            self.assertEqual(db.get(UserTotp, uid).secret, "vault")
            self.assertNotIn(secret, db.get(TotpVault, uid).encrypted)
        with TestClient(self.app) as c:
            c.headers["Origin"] = "http://testserver"
            self.assertEqual(
                c.post(
                    "/api/login",
                    json={"username": "amy", "password": fixture.PW, "otp": codes[0]},
                ).status_code,
                200,
            )
            self.assertEqual(
                c.post(
                    "/api/login",
                    json={"username": "amy", "password": fixture.PW, "otp": codes[0]},
                ).status_code,
                401,
            )

    def test_failed_object_delete_is_durably_queued_and_retry_succeeds(self):
        from unittest.mock import patch
        from app.hardening import drain_deletions

        amy = self.client("amy")
        mid = amy.post(
            "/api/chat/main/0/files", files={"file": ("a.txt", b"hi", "text/plain")}
        ).json()["id"]
        with patch.object(self.app.state.storage, "discard", return_value=False):
            self.assertEqual(amy.delete(f"/api/chat/messages/{mid}").status_code, 200)
        with Session(self.app.state.engine) as db:
            self.assertIsNotNone(db.scalar(select(ObjectDeletion)))
        self.assertEqual(
            drain_deletions(self.app.state.engine, self.app.state.storage)["pending"], 0
        )

    def test_legacy_rollback_restores_a_factor_before_old_code_runs(self):
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "compat", Path("deploy/totp-compat.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        amy = self.client("amy")
        secret = amy.post(
            "/api/account/totp/setup", json={"password": fixture.PW}
        ).json()["secret"]
        self.assertEqual(
            module.compatibility(self.app.state.engine, self.app.state.totp_vault), 1
        )
        self.assertEqual(
            module.compatibility(
                self.app.state.engine, self.app.state.totp_vault, True
            ),
            1,
        )
        from app.security import totp_verify

        with Session(self.app.state.engine) as db:
            row = db.scalar(select(UserTotp))
            self.assertEqual(row.secret, secret)
            self.assertTrue(totp_verify(row.secret, totp_code(secret)))

    def test_missing_encryption_key_does_not_silently_replace_existing_vault_key(self):
        from app.hardening import initialize

        amy = self.client("amy")
        amy.post("/api/account/totp/setup", json={"password": fixture.PW})
        key = self.app.state.settings.data_dir / "totp.key"
        key.unlink()
        with self.assertRaises(RuntimeError):
            initialize(self.app.state.engine, self.app.state.settings)
        self.assertFalse(key.exists())
