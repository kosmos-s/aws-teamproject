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
from .models import (Base, User, BlockedUser, UserActivity, TeamGroup, GroupMember, ProjectAccess,
                     ProjectPolicy, Task, AttachmentOwner, ChatAttachment, ChatReply, ChatReaction,
                     ChatEdit, ChatPin, ChatRead, Profile, UserPreference, UploadRecord, OrcaProject)
from .models import ChangeNotice, NoticeRead

# Backup v2 adds team chat (main + group rooms; private 1:1 messages are excluded), archive state and note edits.
EXTRA = [ProjectArchive, NoteEdit, ChatMessage]
BUSINESS = [Project, Note, Attachment, ProjectArchive, NoteEdit, TeamGroup, GroupMember,
            ProjectAccess, ProjectPolicy, Task, AttachmentOwner, ChatMessage, ChatAttachment,
            ChatReply, ChatReaction, ChatEdit, ChatPin, ChatRead, Profile, UserPreference, UploadRecord, OrcaProject]
BUSINESS += [ChangeNotice,NoticeRead]


def file_inventory(tables):
    files = {r['key']:r['size'] for name in ('attachments','chat_attachments') for r in tables.get(name,[])}
    files.update({r['photo_key']:512*1024 for r in tables.get('profiles',[]) if r.get('photo_key')})
    return files


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
            identities = [dict(r) for r in conn.execute(select(User.id,User.username,User.role)).mappings()]
            if len(identities)>10000: raise ValueError('Too many identities')
            chat_ids = select(ChatMessage.id).where(ChatMessage.room != 'dm')
            for model in BUSINESS:
                rows = []
                query = select(model.__table__)
                if model is ChatMessage:
                    query = query.where(ChatMessage.room != "dm")
                elif model in (ChatAttachment,ChatReply,ChatReaction,ChatEdit):
                    query=query.where(model.message_id.in_(chat_ids))
                    if model is ChatReply:query=query.where(ChatReply.reply_to.in_(chat_ids))
                elif model is ChatPin:
                    query=query.where(ChatPin.message_id.in_(chat_ids))
                elif model is ChatRead:
                    query=query.where(~ChatRead.room_key.startswith('dm:'))
                elif model is UploadRecord:
                    refs=select(Attachment.key).union(
                        select(ChatAttachment.key).where(ChatAttachment.message_id.in_(chat_ids)),
                        select(Profile.photo_key).where(Profile.photo_key.is_not(None)))
                    query=query.where(UploadRecord.key.in_(refs))
                for r in conn.execute(query.limit(10001)).mappings():
                    row = dict(r)
                    estimated += len(json.dumps(row, ensure_ascii=False).encode()) + 4
                    if model in (Attachment, ChatAttachment):
                        estimated += ((row["size"] + 2) // 3) * 4 + 256
                    elif model is Profile and row.get('photo_key'):
                        estimated += ((512*1024+2)//3)*4+256
                    if estimated > budget or len(rows) >= 10000:
                        raise ValueError("Backup exceeds lab size budget")
                    rows.append(row)
                tables[model.__tablename__] = rows
            kept = {r['id'] for r in tables['chat_messages']}
            for name in ('chat_attachments','chat_reactions','chat_edits'):
                tables[name]=[r for r in tables[name] if r['message_id'] in kept]
            tables['chat_replies']=[r for r in tables['chat_replies'] if r['message_id'] in kept and r['reply_to'] in kept]
            tables['chat_pins']=[r for r in tables['chat_pins'] if r['message_id'] in kept]
            tables['chat_reads']=[r for r in tables['chat_reads'] if not r['room_key'].startswith('dm:')]
            used_keys=set(file_inventory(tables))
            tables['upload_records']=[r for r in tables['upload_records'] if r['key'] in used_keys]
            # Preserve old ACLs even when backing up a pre-migration DB.
            policies={r['project_id'] for r in tables['project_policies']}
            for r in tables['project_access']:
                if r['project_id'] not in policies:
                    tables['project_policies'].append({'project_id':r['project_id'],'restricted':1})
                    policies.add(r['project_id'])
        files = {}
        for key,size in file_inventory(tables).items():
            data = storage.get(key, max_bytes=1536 * 1024)
            estimated += ((len(data) + 2) // 3) * 4 - ((size + 2) // 3) * 4
            if estimated > budget:
                raise ValueError("Backup actual objects exceed size budget")
            files[key] = {"content": base64.b64encode(data).decode(), "sha256": hashlib.sha256(data).hexdigest()}
        payload = json.dumps({"version": 3, "tables": tables, "files": files, 'identities':identities,
                              'policy':{'private_dm':'excluded','credentials':'excluded','restored_accounts':'blocked'}}, ensure_ascii=False).encode()
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
        if len(archive)>16*1024*1024: raise ValueError('Archive exceeds lab limit')
        payload = json.loads(archive)
        base = {"projects", "work_notes", "attachments"}
        v2 = base | {m.__tablename__ for m in EXTRA}
        v3={m.__tablename__ for m in BUSINESS}
        if not ((payload["version"] == 1 and set(payload["tables"]) == base) or (payload["version"] == 2 and set(payload["tables"]) == v2) or (payload['version']==3 and set(payload['tables'])==v3)):
            raise ValueError("Unsupported backup")
        tables, files = payload["tables"], payload["files"]
        if any(not isinstance(rows,list) or len(rows)>10000 for rows in tables.values()): raise ValueError('Invalid row count')
        expected_keys = set(file_inventory(tables))
        if expected_keys != set(files):
            raise ValueError("Attachment inventory mismatch")
        decoded = {}
        for key, item in files.items():
            storage.path(key)
            value = base64.b64decode(item["content"], validate=True)
            if len(value)>1536*1024: raise ValueError('Object exceeds size budget')
            if hashlib.sha256(value).hexdigest() != item["sha256"]:
                raise ValueError("Backup checksum mismatch")
            decoded[key] = value
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid backup") from exc
    with engine.begin() as conn:
        selected={m.__tablename__:m.__table__ for m in BUSINESS if m.__tablename__ in tables}
        ordered=[t for t in Base.metadata.sorted_tables if t.name in selected]
        for table in ordered + ([User.__table__] if payload['version']==3 else []):
            if conn.execute(select(table).limit(1)).first():
                raise ValueError("Restore target must be empty")
        if payload['version']==3:
            from .security import password_hash
            identities=payload.get('identities',[])
            if len(identities)>10000: raise ValueError('Too many identities')
            for u in identities:
                if set(u)!={'id','username','role'} or u['role'] not in {'admin','member','viewer'}: raise ValueError('Invalid identity')
                conn.execute(User.__table__.insert().values(**u,password_hash=password_hash(secrets.token_urlsafe(32))))
                conn.execute(BlockedUser.__table__.insert().values(user_id=u['id']))
                conn.execute(UserActivity.__table__.insert().values(user_id=u['id'],must_change=1))
        for table in ordered:
            rows = tables[table.name]
            if rows:
                conn.execute(table.insert(), rows)
        if payload['version']<3:
            # Older formats did not save ACLs. Restrict recovered projects until explicitly reviewed.
            for row in tables['projects']: conn.execute(ProjectPolicy.__table__.insert().values(project_id=row['id'],restricted=1))
        for key, value in decoded.items():
            storage.put(key, value, "application/octet-stream")
    event(engine, "restore", "ok", "Business tables and attachment checksums restored to an empty target")
    return {name: len(rows) for name, rows in tables.items()}
