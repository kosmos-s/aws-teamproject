"""Run the real release shell against a fake host and a deliberately failing app start."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


def shell_path(path):
    value = Path(path).resolve().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


class ReleaseOperationsTests(unittest.TestCase):
    def test_failed_service_initialization_restores_code_and_legacy_factor_compatibility(
        self,
    ):
        bash = (
            Path("C:/Program Files/Git/bin/bash.exe")
            if os.name == "nt"
            else shutil.which("bash")
        )
        if not bash or not Path(bash).exists():
            self.skipTest("bash unavailable")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            host = root / "host"
            host.mkdir()
            (host / "app").mkdir()
            (host / ".venv/bin").mkdir(parents=True)
            (host / "app/value.py").write_text("old\n")
            (host / "requirements.lock").write_text("")
            stub = root / "commands"
            stub.mkdir()

            def script(path, text):
                path.write_text("#!/bin/bash\n" + text, encoding="utf-8", newline="\n")
                path.chmod(0o755)

            script(stub / "systemctl", "exit 0\n")
            script(stub / "curl", "exit 0\n")
            script(stub / "python3", 'exec "$REAL_RELEASE_PYTHON" "$@"\n')
            script(
                stub / "systemd-run",
                'while [[ "$#" -gt 0 ]]; do\n case "$1" in -p) shift 2;; --*) shift;; *) exec "$@";; esac\ndone\n',
            )
            script(
                host / ".venv/bin/python",
                'if [[ "${1:-}" == -m && "${2:-}" == pip ]]; then\n "$REAL_RELEASE_PYTHON" -c \'from pathlib import Path; Path("installed-package-mode").write_text("public package")\'\n exit 0\nfi\nif [[ "${1:-}" == -c ]]; then exit 9; fi\nexec "$REAL_RELEASE_PYTHON" "$@"\n',
            )
            helper = b"""from pathlib import Path
import os
if os.name != 'nt':
    assert Path(__file__).parent.stat().st_mode & 0o005 == 0o005
Path('factor-compatibility-restored').write_text('yes')
"""
            files = {
                "app/value.py": b"new\n",
                "requirements.lock": b"",
                "deploy/totp-compat.py": helper,
            }
            manifest = {
                "base": {
                    "app/value.py": hashlib.sha256(b"old\n").hexdigest(),
                    "requirements.lock": hashlib.sha256(b"").hexdigest(),
                },
                "files": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in files.items()
                },
            }
            archive = root / "release.tgz"
            with tarfile.open(archive, "w:gz") as tar:
                for name, data in {
                    **files,
                    "release-manifest.json": json.dumps(manifest).encode(),
                }.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o644
                    tar.addfile(info, io.BytesIO(data))
            # Only replace fixed host paths; run the production shell's validation/traps/restore as written.
            source = Path("deploy/portal-release.sh").read_text(encoding="utf-8")
            source = source.replace(
                "root=/opt/kosmos-portal", "root=" + shell_path(host)
            )
            source = source.replace(
                "/var/tmp/kosmos-before-review-", shell_path(root) + "/before-"
            )
            source = source.replace(
                "/var/tmp/kosmos-review-release.", shell_path(root) + "/stage."
            )
            runner = root / "run.sh"
            runner.write_text(source, encoding="utf-8", newline="\n")
            env = dict(os.environ, REAL_RELEASE_PYTHON=shell_path(sys.executable))
            result = subprocess.run(
                [
                    str(bash),
                    "-c",
                    'export PATH="$1:$PATH"; exec bash "$2" "$3"',
                    "release-test",
                    shell_path(stub),
                    shell_path(runner),
                    shell_path(archive),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=40,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                (host / "app/value.py").read_text(),
                "old\n",
                result.stdout + result.stderr,
            )
            self.assertTrue(
                (host / "factor-compatibility-restored").exists(),
                result.stdout + result.stderr,
            )
            if os.name != "nt":
                self.assertEqual(
                    (host / "installed-package-mode").stat().st_mode & 0o777, 0o644
                )
