"""Read-only preflight; never generates, prints or enrolls TOTP secrets."""
import argparse
import json
import re
from pathlib import Path


def check(version_text, miniserv_text):
    match = re.fullmatch(r"(\d+)\.(\d+)", version_text.strip())
    version_ok = bool(match and tuple(map(int, match.groups())) >= (2, 640))
    config = dict(line.split("=", 1) for line in miniserv_text.splitlines() if "=" in line and not line.startswith("#"))
    return {"version_at_least_2_640": version_ok, "loopback_only": config.get("bind") == "127.0.0.1", "totp_enrollment": "requires user authenticator registration; not assessed", "basic_auth_bypass_advisory": "GHSA-qpww-fff2-6fgv; verify patched version before enrollment"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args()
    result = check((args.root / "usr/share/webmin/version").read_text(), (args.root / "etc/webmin/miniserv.conf").read_text())
    print(json.dumps(result))
    if not result["version_at_least_2_640"] or not result["loopback_only"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
