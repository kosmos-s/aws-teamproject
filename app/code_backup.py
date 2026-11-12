"""Operator-only Git snapshot. Never executes code while restoring."""
import argparse
import base64
import hashlib
import json
import re
import fnmatch
import subprocess
from pathlib import Path, PurePosixPath

LIMIT = 16 * 1024 * 1024
FILE_LIMIT = 1024 * 1024


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Invalid backup path")
    parts = name.split("/")
    if any(p in {"", ".", ".."} for p in parts) or PurePosixPath(name).is_absolute():
        raise ValueError("Unsafe backup path")
    for part in parts:
        lower = part.lower()
        if part.endswith((" ", ".")) or any(ord(c) < 32 for c in part) or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", lower):
            raise ValueError("Windows-unsafe backup path")
        if lower in {".git", ".local", ".aws", ".ssh", ".codex", "data", "backups", ".venv", "node_modules", "vendor", "__pycache__", ".pytest_cache", ".coverage", ".git-credentials"} or (lower.startswith(".env") and lower != ".env.example") or any(fnmatch.fnmatchcase(lower, pattern) for pattern in ["*.key", "*.pem", "*.db*", "*.sqlite*", "*.log", "*.zip", "*.tar.gz", "*.pyc"]):
            raise ValueError("Sensitive or generated path in Git snapshot")
    return name


def backup_code(repo):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL, timeout=30)
    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("ls-tree", "-rz", commit).split(b"\x00")
    files, total = [], 0
    for row in filter(None, tree):
        metadata, raw_name = row.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = safe_name(raw_name.decode("utf-8"))
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Links and submodules are not included")
        size = int(git("cat-file", "-s", oid))
        total += size
        if size > FILE_LIMIT or total > 8 * 1024 * 1024 or len(files) >= 5000:
            raise ValueError("Git snapshot exceeds lab size budget")
        content = git("cat-file", "blob", oid)
        files.append({"path": name, "content": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest(), "executable": mode == "100755"})
    archive = json.dumps({"kind": "git-tracked-code", "version": 1, "commit": commit, "files": files}).encode()
    if len(archive) > LIMIT:
        raise ValueError("Archive exceeds 16 MiB")
    return archive


def restore_code(archive, destination):
    if len(archive) > LIMIT:
        raise ValueError("Archive exceeds 16 MiB")
    try:
        payload = json.loads(archive)
        if payload["kind"] != "git-tracked-code" or payload["version"] != 1 or not re.fullmatch(r"[a-f0-9]{40,64}", payload["commit"]):
            raise ValueError("Invalid snapshot")
        if not isinstance(payload["files"], list) or len(payload["files"]) > 5000:
            raise ValueError("Invalid inventory")
        decoded, names, total = [], set(), 0
        for item in payload["files"]:
            name = safe_name(item["path"])
            if name.casefold() in names:
                raise ValueError("Duplicate backup path")
            names.add(name.casefold())
            content = base64.b64decode(item["content"], validate=True)
            total += len(content)
            if len(content) > FILE_LIMIT or total > 8 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != item["sha256"] or not isinstance(item["executable"], bool):
                raise ValueError("Invalid object size or checksum")
            decoded.append((name, content, item["executable"]))
        # Reject file/directory collisions before creating any output.
        for name in names:
            if any(parent.as_posix().casefold() in names for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
                raise ValueError("Conflicting backup paths")
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid archive") from exc
    destination = Path(destination)
    if destination.is_symlink() or destination.exists():
        raise ValueError("Restore requires a new directory")
    if any(parent.is_symlink() for parent in destination.absolute().parents):
        raise ValueError("Symlink parent is not allowed")
    destination.mkdir(mode=0o700, parents=True)
    for name, content, executable in decoded:
        path = destination / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(0o700 if executable else 0o600)
    return {"commit": payload["commit"], "files": len(decoded), "bytes": total}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("backup")
    save.add_argument("repo", type=Path)
    save.add_argument("archive", type=Path)
    save.add_argument("--s3", action="store_true", help="Also upload using configured instance role")
    load = sub.add_parser("restore")
    load.add_argument("archive", type=Path)
    load.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "backup":
        archive = backup_code(args.repo)
        with args.archive.open("xb") as stream:
            stream.write(archive)
        args.archive.chmod(0o600)
        if args.s3:
            import secrets
            from .config import Settings
            from .storage import Storage
            settings = Settings.from_env()
            if not settings.bucket:
                raise ValueError("S3_BUCKET required")
            key = "backups/" + secrets.token_hex(16) + ".json"
            Storage(settings).put(key, archive, "application/json")
            print("S3 key:", key)
        print("Code snapshot saved; uncommitted/untracked changes excluded")
    else:
        if args.archive.stat().st_size > LIMIT:
            raise ValueError("Archive exceeds limit")
        print(json.dumps(restore_code(args.archive.read_bytes(), args.destination)))


if __name__ == "__main__":
    main()
