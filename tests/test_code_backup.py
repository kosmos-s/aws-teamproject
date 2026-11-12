import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.code_backup import backup_code, restore_code, safe_name


class CodeBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init", "-q")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "test snapshot")

    def tearDown(self):
        # Windows Git object files can be read-only; normalize our temporary files.
        for path in self.root.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        self.tmp.cleanup()

    def test_git_code_roundtrip_excludes_untracked_credentials(self):
        (self.repo / "main.py").write_text("print('recovered')\n")
        self.commit()
        (self.repo / ".env").write_text("PRIVATE_DO_NOT_BACK_UP=yes")
        archive = backup_code(self.repo)
        self.assertNotIn(b"PRIVATE_DO_NOT_BACK_UP", archive)
        result = restore_code(archive, self.root / "restored")
        self.assertEqual(result["files"], 1)
        self.assertEqual((self.root / "restored/main.py").read_bytes(), self.git("show", "HEAD:main.py"))
        self.assertEqual(subprocess.check_output([sys.executable, str(self.root / "restored/main.py")]).strip(), b"recovered")
        with self.assertRaises(ValueError):
            restore_code(archive, self.root / "restored")

    def test_tracked_secret_path_is_rejected(self):
        (self.repo / ".env").write_text("SECRET=private")
        self.commit()
        with self.assertRaises(ValueError):
            backup_code(self.repo)

    def test_generated_and_windows_unsafe_paths_are_rejected(self):
        for name in ["vendor/tool", "__pycache__/cache.pyc", "cache.db-wal", "cache.sqlite3", "dump.zip", "../bad", ".. /escape", "CON.txt"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)

    def test_snapshot_uses_captured_commit_when_head_changes(self):
        (self.repo / "main.py").write_text("old\n")
        self.commit()
        original = subprocess.check_output
        def advance(command, **kwargs):
            result = original(command, **kwargs)
            if command[-2:] == ["rev-parse", "HEAD"]:
                (self.repo / "main.py").write_text("new\n")
                self.commit()
            return result
        with patch("app.code_backup.subprocess.check_output", side_effect=advance):
            payload = json.loads(backup_code(self.repo))
        self.assertEqual(base64.b64decode(payload["files"][0]["content"]), b"old\n")

    def test_restore_rejects_traversal_and_corruption_without_writing(self):
        value = b"bad"
        for name, digest in [("../escape", hashlib.sha256(value).hexdigest()), ("safe.py", "0" * 64)]:
            payload = {"kind": "git-tracked-code", "version": 1, "commit": "a" * 40, "files": [{"path": name, "content": base64.b64encode(value).decode(), "sha256": digest, "executable": False}]}
            with self.assertRaises(ValueError):
                restore_code(json.dumps(payload).encode(), self.root / "target")
            self.assertFalse((self.root / "target").exists())
