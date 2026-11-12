"""Operator-only commands. No shell commands are exposed through the web API."""
import base64
import hashlib
import json
import secrets
import shutil
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .models import Project, Note, Attachment, Event, ChatMessage, ProjectArchive, NoteEdit

# Backup v2 adds team chat (main + group rooms; private 1:1 messages are excluded), archive state and note edits.
EXTRA = [ProjectArchive, NoteEdit, ChatMessage]


def event(engine, kind, state, summary):
    with Session(engine) as db:
        db.add(Event(kind=kind, state=state, summary=summary,
                     created=datetime.now(timezone.utc).isoformat()))
        db.commit()


def probe_orca():
    try:
        with socket.create_connection(("127.0.0.1", 6768), timeout=3):
            return True
    except OSError:
        return False


def monitor(engine, data_dir, probe=probe_orca):
    ok = probe()
    usage = shutil.disk_usage(data_dir)
    disk_percent = round(usage.used / usage.total * 100, 1)
    state = "ok" if ok and disk_percent < 90 else "failed"
    summary = f"Orca TCP={'reachable' if ok else 'unreachable'}; disk={disk_percent}%"
    try:
        import psutil
        summary += f"; CPU={psutil.cpu_percent(interval=0.2)}%; RAM={psutil.virtual_memory().percent}%"
    except ImportError:
        summary += "; CPU/RAM=unavailable"
    event(engine, "monitor", state, summary)
    # Keep at most 3 days of routine checks; backups have their own S3 lifecycle.
    cutoff = datetime.fromtimestamp(time.time() - 3 * 86400, timezone.utc).isoformat()
    with Session(engine) as db:
        db.execute(delete(Event).where(Event.kind == "monitor", Event.created < cutoff))
        db.commit()
    return {"state": state, "summary": summary}


def backup(engine, storage):
    try:
        tables = {}
        budget = 16 * 1024 * 1024
        estimated = 1024
        with engine.begin() as conn:
            for model in [Project, Note, Attachment] + EXTRA:
                rows = []
                query = select(model.__table__)
                if model is ChatMessage:
                    query = query.where(ChatMessage.room != "dm")
                for r in conn.execute(query.limit(10001)).mappings():
                    row = dict(r)
                    if model is ChatMessage:
                        # Accounts are not backed up; keep the author by name only.
                        row["sender_id"] = None
                        row["recipient_id"] = None
                    estimated += len(json.dumps(row, ensure_ascii=False).encode()) + 4
                    if model == Attachment:
                        estimated += ((row["size"] + 2) // 3) * 4 + 256
                    if estimated > budget or len(rows) >= 10000:
                        raise ValueError("Backup exceeds lab size budget")
                    rows.append(row)
                tables[model.__tablename__] = rows
        files = {}
        for row in tables["attachments"]:
            data = storage.get(row["key"], max_bytes=1024 * 1024)
            estimated += ((len(data) + 2) // 3) * 4 - ((row["size"] + 2) // 3) * 4
            if estimated > budget:
                raise ValueError("Backup actual objects exceed size budget")
            files[row["key"]] = {"content": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
        payload = json.dumps({"version": 2, "tables": tables, "files": files}, ensure_ascii=False).encode()
        if len(payload) > 16 * 1024 * 1024:
            raise ValueError("Backup exceeds 16 MiB lab limit")
        key = "backups/" + secrets.token_hex(16) + ".json"
        storage.put(key, payload, "application/json")
        event(engine, "backup", "ok", f"Object={key}; bytes={len(payload)}; sha256={hashlib.sha256(payload).hexdigest()}")
        return payload
    except Exception:
        event(engine, "backup", "failed", "Backup failed; no successful recovery point recorded")
        raise


def restore(engine, storage, archive):
    """Restore business data only into a fresh DB; never restore credentials/sessions."""
    try:
        payload = json.loads(archive)
        base = {"projects", "work_notes", "attachments"}
        v2 = base | {m.__tablename__ for m in EXTRA}
        if not ((payload["version"] == 1 and set(payload["tables"]) == base) or (payload["version"] == 2 and set(payload["tables"]) == v2)):
            raise ValueError("Unsupported backup")
        tables, files = payload["tables"], payload["files"]
        expected_keys = {row["key"] for row in tables["attachments"]}
        if expected_keys != set(files):
            raise ValueError("Attachment inventory mismatch")
        decoded = {}
        for key, item in files.items():
            storage.path(key)
            value = base64.b64decode(item["content"], validate=True)
            if hashlib.sha256(value).hexdigest() != item["sha256"]:
                raise ValueError("Backup checksum mismatch")
            decoded[key] = value
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid backup") from exc
    with engine.begin() as conn:
        models = [m for m in [Project, Note, Attachment] + EXTRA if m.__tablename__ in tables]
        for model in models:
            if conn.execute(select(model.__table__).limit(1)).first():
                raise ValueError("Restore target must be empty")
        for model in models:
            rows = tables[model.__tablename__]
            if rows:
                conn.execute(model.__table__.insert(), rows)
        for key, value in decoded.items():
            storage.put(key, value, "application/octet-stream")
    event(engine, "restore", "ok", "Business tables and attachment checksums restored to an empty target")
    return {name: len(rows) for name, rows in tables.items()}
