"""Tests use only temporary files; no host privileges or AWS."""

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


def deploy_module(filename):
    path = Path(__file__).resolve().parents[1] / "deploy" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(os.name == "posix", "Linux deployment filesystem checks")
class FolderSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.write = deploy_module("orca-link-worker.py").write_folder_snapshot
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.directory = self.root / "snapshot"
        self.directory.mkdir(mode=0o750)
        self.directory.chmod(0o750)

    def test_publishes_read_only_group_snapshot_and_updates_it(self):
        path = self.directory / "orca-folders.json"
        self.write({"folders": []}, self.directory)
        self.write({"folders": [{"name": "sample", "git": True}]}, self.directory)
        self.assertEqual(json.loads(path.read_text())["folders"], [{"name": "sample", "git": True}])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(list(self.directory.iterdir()), [path])

    def test_refuses_untrusted_writable_directory(self):
        self.directory.chmod(0o770)
        with self.assertRaises(PermissionError):
            self.write({}, self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_refuses_symlink_directory_and_never_follows_snapshot_link(self):
        link = self.root / "linked-directory"
        link.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(OSError):
            self.write({}, link)
        control = self.root / "outside.txt"
        control.write_text("outside stays unchanged")
        snapshot = self.directory / "orca-folders.json"
        snapshot.symlink_to(control)
        self.write({"folders": []}, self.directory)
        self.assertFalse(snapshot.is_symlink())
        self.assertEqual(control.read_text(), "outside stays unchanged")
