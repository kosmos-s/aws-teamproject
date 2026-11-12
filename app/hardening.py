"""Single-worker coordination and persistent security policy; no command execution."""

import os
import secrets
import threading
import time
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete, func, or_
from sqlalchemy.orm import Session

from .models import (
    User,
    LoginSession,
    BlockedUser,
    UserActivity,
    SessionActivity,
    ProjectAccess,
    ProjectPolicy,
    UserTotp,
    TotpVault,
    RecoveryCode,
    UserPreference,
    ObjectDeletion,
    UploadRecord,
    Event,
    Base,
)
from .security import token_hash, verify_password

# Sync FastAPI endpoints execute concurrently in threads even with one worker.
LOGIN_LOCK = threading.RLock()
REACTION_LOCK = threading.RLock()
UPLOAD_LOCK = threading.RLock()


def serialized(lock):
    from functools import wraps

    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)

        return run

    return decorate


def idle_seconds():
    try:
        return max(5, int(os.getenv("IDLE_MINUTES", "30"))) * 60
    except ValueError:
        return 1800


def session_policy(db, row, *, developer=False):
    if not row or row.expires <= time.time():
        return None
    u = db.get(User, row.user_id)
    if not u or db.get(BlockedUser, u.id):
        return None
    a = db.get(SessionActivity, row.token_hash)
    # Legacy sessions are invalidated at migration, never silently renewed.
    if not a or time.time() - a.last_active > idle_seconds():
        return None
    if developer:
        act = db.get(UserActivity, u.id)
        if u.role not in {"admin", "member"} or (act and act.must_change):
            return None
    return u


def live_developer(db, hashed):
    # Same persisted idle/expiry/blocked/forced-password policy in one indexed query.
    return (
        db.scalar(
            select(User.id)
            .join(LoginSession, LoginSession.user_id == User.id)
            .join(
                SessionActivity, SessionActivity.token_hash == LoginSession.token_hash
            )
            .outerjoin(BlockedUser, BlockedUser.user_id == User.id)
            .outerjoin(UserActivity, UserActivity.user_id == User.id)
            .where(
                LoginSession.token_hash == hashed,
                LoginSession.expires > time.time(),
                SessionActivity.last_active > time.time() - idle_seconds(),
                User.role.in_(["admin", "member"]),
                BlockedUser.user_id.is_(None),
                or_(UserActivity.user_id.is_(None), UserActivity.must_change == 0),
            )
        )
        is not None
    )


class AttemptLimit:
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = {}

    def check(self, key):
        with self.lock:
            now = time.time()
            self.attempts = {
                k: [t for t in v if now - t < 300]
                for k, v in self.attempts.items()
                if v and now - v[-1] < 300
            }
            recent = self.attempts.setdefault(key, [])
            if len(recent) >= 5:
                raise HTTPException(
                    429,
                    "Too many verification attempts",
                    headers={"Retry-After": str(max(1, int(301 - now + recent[0])))},
                )
            recent.append(now)


def initialize(engine, settings):
    from .models import ChatMessage

    for index in ChatMessage.__table__.indexes:
        if index.name in {"ix_chat_room_id", "ix_chat_dm_recipient_sender_id"}:
            index.create(engine, checkfirst=True)
    # Outside the DB and business backups, readable only by the service account.
    keyfile = settings.data_dir / "totp.key"
    if not keyfile.exists():
        with Session(engine) as db:
            if db.scalar(select(TotpVault.user_id).limit(1)) is not None:
                raise RuntimeError(
                    "Factor encryption key unavailable; operator recovery required"
                )
        try:
            fd = os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # A concurrent CLI may be creating the first key. Never overwrite it.
            for _ in range(20):
                if len(keyfile.read_bytes()) == 44:
                    break
                time.sleep(0.01)
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
    if os.name != "nt":
        keyfile.chmod(0o600)
    vault = Fernet(keyfile.read_bytes())
    with Session(engine) as db:
        from .models import (
            Attachment,
            AttachmentOwner,
            ChatAttachment,
            ChatMessage,
            Profile,
        )

        known = set(db.scalars(select(UploadRecord.key)))
        owners = {
            r.attachment_id: r.uploaded_by for r in db.scalars(select(AttachmentOwner))
        }
        for f in db.scalars(select(Attachment)):
            if f.key not in known:
                db.add(
                    UploadRecord(
                        key=f.key,
                        username=owners.get(f.id, "(legacy)"),
                        scope=f"project:{f.project_id}",
                        size=f.size,
                        created=time.time(),
                    )
                )
                known.add(f.key)
        for f, m in db.execute(
            select(ChatAttachment, ChatMessage).join(
                ChatMessage, ChatMessage.id == ChatAttachment.message_id
            )
        ):
            if f.key not in known:
                scope = (
                    m.room
                    if m.room != "dm"
                    else f"dm:{min(m.sender_id or 0,m.recipient_id or 0)}-{max(m.sender_id or 0,m.recipient_id or 0)}"
                )
                db.add(
                    UploadRecord(
                        key=f.key,
                        username=m.sender_name,
                        scope=scope,
                        size=f.size,
                        created=time.time(),
                    )
                )
                known.add(f.key)
        names = {u.id: u.username for u in db.scalars(select(User))}
        for p in db.scalars(select(Profile).where(Profile.photo_key.is_not(None))):
            if p.photo_key not in known:
                db.add(
                    UploadRecord(
                        key=p.photo_key,
                        username=names.get(p.user_id, "(legacy)"),
                        scope=f"profile:{p.user_id}",
                        size=512 * 1024,
                        created=time.time(),
                    )
                )
                known.add(p.photo_key)
        for pid in set(db.scalars(select(ProjectAccess.project_id))):
            if not db.get(ProjectPolicy, pid):
                db.add(ProjectPolicy(project_id=pid, restricted=1))
        for row in db.scalars(select(UserTotp)):
            if row.secret != "vault":
                old = db.get(TotpVault, row.user_id)
                if old:
                    old.encrypted = vault.encrypt(row.secret.encode()).decode()
                else:
                    db.add(
                        TotpVault(
                            user_id=row.user_id,
                            encrypted=vault.encrypt(row.secret.encode()).decode(),
                        )
                    )
                row.secret = "vault"
        # Existing sessions lack trustworthy activity timestamps: require a new login.
        db.execute(
            delete(LoginSession).where(
                LoginSession.token_hash.not_in(select(SessionActivity.token_hash))
            )
        )
        db.execute(
            delete(SessionActivity).where(
                SessionActivity.token_hash.not_in(select(LoginSession.token_hash))
            )
        )
        db.commit()
    return vault


def maintenance(engine, storage):
    """Existing monitor timer calls this; no additional AWS service or user command."""
    from .models import ChatMessage, ChatPin

    days = int(os.getenv("CHAT_RETENTION_DAYS", "0"))
    if days > 0:
        from datetime import datetime, timezone
        from .suite import purge_messages

        cutoff = datetime.fromtimestamp(
            time.time() - days * 86400, timezone.utc
        ).isoformat()
        with Session(engine) as db:
            ids = list(
                db.scalars(
                    select(ChatMessage.id)
                    .where(
                        ChatMessage.created < cutoff,
                        ChatMessage.id.not_in(select(ChatPin.message_id)),
                    )
                    .limit(500)
                )
            )
            purge_messages(db, ids)
            db.execute(delete(ChatMessage).where(ChatMessage.id.in_(ids)))
            db.commit()
    return drain_deletions(engine, storage)


def totp_secret(db, vault, row):
    saved = db.get(TotpVault, row.user_id)
    if saved:
        return vault.decrypt(saved.encrypted.encode()).decode()
    if row.secret != "vault":
        return row.secret  # fixture/legacy, migrated at service startup
    raise HTTPException(503, "Two-factor unavailable")


def require_password(db, username, password):
    u = db.scalar(select(User).where(User.username == username))
    if not u or not verify_password(password, u.password_hash):
        raise HTTPException(403, "Current password incorrect")
    return u


def issue_recovery(db, uid):
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == uid))
    codes = [secrets.token_hex(8) for _ in range(8)]
    db.add_all([RecoveryCode(user_id=uid, code_hash=token_hash(c)) for c in codes])
    return codes


def queue_delete(db, key):
    if not db.get(ObjectDeletion, key):
        db.add(ObjectDeletion(key=key, created=time.time(), attempts=0))
    db.execute(delete(UploadRecord).where(UploadRecord.key == key))


def drain_deletions(engine, storage, limit=100):
    with Session(engine) as db:
        rows = list(
            db.scalars(
                select(ObjectDeletion).order_by(ObjectDeletion.created).limit(limit)
            )
        )
        ok = 0
        for r in rows:
            if storage.discard(r.key):
                db.delete(r)
                ok += 1
            else:
                r.attempts += 1
        db.commit()
        return {
            "removed": ok,
            "pending": db.scalar(select(func.count(ObjectDeletion.key))) or 0,
        }


def record_upload(db, key, username, scope, size):
    """Call under UPLOAD_LOCK; account total + group/room total + global budget."""
    user_limit = int(os.getenv("UPLOAD_USER_MIB", "20")) * 1024 * 1024
    scope_limit = int(os.getenv("UPLOAD_SCOPE_MIB", "40")) * 1024 * 1024
    total_limit = int(os.getenv("UPLOAD_TOTAL_MIB", "100")) * 1024 * 1024
    for condition, limit in [
        (UploadRecord.username == username, user_limit),
        (UploadRecord.scope == scope, scope_limit),
        (True, total_limit),
    ]:
        used = (
            db.scalar(
                select(func.coalesce(func.sum(UploadRecord.size), 0)).where(condition)
            )
            or 0
        )
        if used + size > limit:
            raise HTTPException(413, "Storage quota exceeded")
    db.add(
        UploadRecord(
            key=key, username=username, scope=scope, size=size, created=time.time()
        )
    )


class PreferenceInput(BaseModel):
    notify: Literal["all", "mentions", "off"] = "all"
    sound: bool = True


def install_routes(app, authenticated, admin):
    engine = app.state.engine

    @app.post("/api/activity")
    def activity(user=Depends(authenticated)):
        with Session(engine) as db:
            a = db.get(SessionActivity, user["session_hash"])
            if a:
                a.last_active = time.time()
                db.commit()
        return {"ok": True}

    @app.get("/api/account/preferences")
    def preferences(user=Depends(authenticated)):
        with Session(engine) as db:
            r = db.get(UserPreference, user["id"])
            return {
                "notify": r.notify if r else "all",
                "sound": bool(r.sound) if r else True,
            }

    @app.put("/api/account/preferences")
    def set_preferences(data: PreferenceInput, user=Depends(authenticated)):
        with Session(engine) as db:
            r = db.get(UserPreference, user["id"])
            if not r:
                r = UserPreference(user_id=user["id"])
                db.add(r)
            r.notify, r.sound = data.notify, int(data.sound)
            db.commit()
        return data.model_dump()

    @app.get("/api/account/storage")
    def usage(user=Depends(authenticated)):
        with Session(engine) as db:
            size = (
                db.scalar(
                    select(func.sum(UploadRecord.size)).where(
                        UploadRecord.username == user["username"]
                    )
                )
                or 0
            )
            return {
                "used_bytes": size,
                "limit_bytes": int(os.getenv("UPLOAD_USER_MIB", "20")) * 1024 * 1024,
            }

    @app.get("/api/admin/diagnostics")
    def diagnostics(actor=Depends(admin)):
        # Explicit allowlist, no environment, database URL, names, message bodies or exception text.
        with Session(engine) as db:
            counts = {
                t.name: db.scalar(select(func.count()).select_from(t))
                for t in Base.metadata.sorted_tables
            }
            return {
                "schema_tables": len(counts),
                "counts": counts,
                "single_worker": True,
                "idle_seconds": idle_seconds(),
                "storage": "s3" if app.state.settings.bucket else "local",
                "pending_file_deletions": counts.get("object_deletions", 0),
            }
