"""2026-11-12 collaboration suite: chat files/replies/reactions/search/pins, kanban tasks,
profiles, and TOTP second factor. Access rules mirror the existing chat and project rules."""
import secrets
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Query, UploadFile, File, Form, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, func, or_, and_
from sqlalchemy.orm import Session

from .models import (User, BlockedUser, ChatMessage, ChatRead, ChatEdit, ChatAttachment, ChatReply, ChatReaction,
                     ChatPin, GroupMember, TeamGroup, Task, Profile, UserTotp, Project, Event)
from .security import totp_new_secret, totp_verify

REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"]
CHAT_FILE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                   ".pdf": "application/pdf", ".txt": "text/plain"}
PHOTO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def now():
    return datetime.now(timezone.utc).isoformat()


def purge_messages(db, ids):
    """Remove everything that references these chat messages (before deleting the messages)."""
    ids = list(ids)
    if not ids:
        return []
    keys = list(db.scalars(select(ChatAttachment.key).where(ChatAttachment.message_id.in_(ids))))
    for model, col in [(ChatAttachment, ChatAttachment.message_id), (ChatReaction, ChatReaction.message_id),
                       (ChatEdit, ChatEdit.message_id), (ChatPin, ChatPin.message_id)]:
        db.execute(delete(model).where(col.in_(ids)))
    db.execute(delete(ChatReply).where(or_(ChatReply.message_id.in_(ids), ChatReply.reply_to.in_(ids))))
    return keys


def forget_user_suite(db, user_id):
    db.execute(delete(ChatReaction).where(ChatReaction.user_id == user_id))
    db.execute(delete(Profile).where(Profile.user_id == user_id))
    db.execute(delete(UserTotp).where(UserTotp.user_id == user_id))


def me_row(db, user):
    row = db.scalar(select(User).where(User.username == user["username"]))
    if not row:
        raise HTTPException(401, "Login required")
    return row


def can_read_message(db, me, m):
    if m.room == "main":
        return True
    if m.room == "dm":
        return me.id in (m.sender_id, m.recipient_id)
    if m.room.startswith("g") and m.room[1:].isdigit():
        return db.get(GroupMember, (int(m.room[1:]), me.id)) is not None
    return False


def pin_key(m):
    if m.room == "dm":
        a, b = sorted([m.sender_id or 0, m.recipient_id or 0])
        return f"dm:{a}-{b}"
    return m.room


def extras_for(db, rows):
    """Replies, reactions and attachments for a page of messages (used by collab.serialize)."""
    ids = [m.id for m in rows]
    if not ids:
        return {}
    replies = {r.message_id: r.reply_to for r in db.scalars(select(ChatReply).where(ChatReply.message_id.in_(ids)))}
    quoted = {}
    if replies:
        for q in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(set(replies.values())))):
            gone = db.get(ChatEdit, q.id)
            quoted[q.id] = {"id": q.id, "sender": q.sender_name, "body": "" if (gone and gone.deleted) else q.body[:120]}
    reactions = {}
    for r in db.scalars(select(ChatReaction).where(ChatReaction.message_id.in_(ids))):
        reactions.setdefault(r.message_id, []).append(r)
    files = {a.message_id: a for a in db.scalars(select(ChatAttachment).where(ChatAttachment.message_id.in_(ids)))}
    return {"replies": replies, "quoted": quoted, "reactions": reactions, "files": files}


def extra_fields(m, uid, extras):
    if not extras:
        return {}
    out = {}
    rt = extras["replies"].get(m.id)
    if rt:
        out["reply_to"] = extras["quoted"].get(rt, {"id": rt, "sender": "", "body": ""})
    rs = extras["reactions"].get(m.id, [])
    if rs:
        counts = {}
        for r in rs:
            c = counts.setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "mine": False})
            c["count"] += 1
            c["mine"] = c["mine"] or r.user_id == uid
        out["reactions"] = sorted(counts.values(), key=lambda c: REACTIONS.index(c["emoji"]) if c["emoji"] in REACTIONS else 99)
    f = extras["files"].get(m.id)
    if f:
        out["file"] = {"name": f.name, "size": f.size, "media_type": f.media_type, "image": f.media_type.startswith("image/")}
    return out


class ReactInput(BaseModel):
    emoji: str = Field(max_length=16)


class PinInput(BaseModel):
    message_id: int


class TaskInput(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    assignee: Optional[str] = Field(default=None, max_length=80)
    due: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("title")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("blank")
        return v.strip()


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[Literal["todo", "doing", "done"]] = None
    assignee: Optional[str] = Field(default=None, max_length=80)
    due: Optional[str] = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class ProfileInput(BaseModel):
    display_name: str = Field(default="", max_length=40)
    team: str = Field(default="", max_length=60)


class CodeInput(BaseModel):
    code: str = Field(min_length=6, max_length=10)


def install_suite_routes(app, authenticated, admin):
    engine = app.state.engine
    storage = app.state.storage

    def bump():
        app.state.change_version = getattr(app.state, "change_version", 0) + 1

    # ---------------- chat: files ----------------
    @app.post("/api/chat/{kind}/{rid}/files", status_code=201)
    def chat_file(kind: Literal["main", "group", "dm"], rid: int, file: UploadFile = File(...),
                  body: str = Form(default="", max_length=500), user=Depends(authenticated)):
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        media = CHAT_FILE_TYPES.get(Path(name).suffix.lower())
        if not media or len(name) > 180 or any(ord(c) < 32 for c in name):
            raise HTTPException(415, "Allowed: png, jpg, gif, pdf, txt")
        content = file.file.read(1536 * 1024 + 1)
        file.file.close()
        if len(content) > 1536 * 1024:
            raise HTTPException(413, "Maximum 1.5 MiB")
        with Session(engine) as db:
            me = me_row(db, user)
            if kind == "main":
                room, recipient, read_key = "main", None, "main"
            elif kind == "group":
                if not db.get(TeamGroup, rid) or not db.get(GroupMember, (rid, me.id)):
                    raise HTTPException(404, "Group not found")
                room, recipient, read_key = f"g{rid}", None, f"g:{rid}"
            else:
                peer = db.get(User, rid)
                if not peer or peer.id == me.id:
                    raise HTTPException(404, "User not found")
                if db.get(BlockedUser, peer.id):
                    raise HTTPException(409, "Recipient is blocked")
                room, recipient, read_key = "dm", peer.id, f"dm:{peer.id}"
            key = "attachments/" + secrets.token_hex(16)
            try:
                storage.put(key, content, media)
            except Exception:
                raise HTTPException(503, "Storage unavailable")
            m = ChatMessage(room=room, sender_id=me.id, sender_name=me.username, recipient_id=recipient,
                            body=body.strip(), created=now())
            db.add(m); db.flush()
            db.add(ChatAttachment(message_id=m.id, key=key, name=name, media_type=media, size=len(content)))
            r = db.get(ChatRead, (me.id, read_key))
            if r is None:
                db.add(ChatRead(user_id=me.id, room_key=read_key, last_id=m.id))
            else:
                r.last_id = max(r.last_id, m.id)
            db.commit()
            return {"id": m.id}

    @app.get("/api/chat/files/{message_id}")
    def chat_file_get(message_id: int, download: int = 0, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            m = db.get(ChatMessage, message_id)
            f = db.get(ChatAttachment, message_id)
            if not m or not f or not can_read_message(db, me, m):
                raise HTTPException(404, "File not found")
            try:
                content = storage.get(f.key)
            except Exception:
                raise HTTPException(503, "Storage unavailable")
            from urllib.parse import quote
            inline = f.media_type.startswith("image/") and not download
            disp = ("inline" if inline else "attachment") + "; filename*=UTF-8''" + quote(f.name, safe="")
            return Response(content, media_type=f.media_type if inline else "application/octet-stream",
                            headers={"Content-Disposition": disp})

    # ---------------- chat: reactions ----------------
    @app.post("/api/chat/messages/{message_id}/react")
    def react(message_id: int, data: ReactInput, user=Depends(authenticated)):
        if data.emoji not in REACTIONS:
            raise HTTPException(422, "Invalid input")
        with Session(engine) as db:
            me = me_row(db, user)
            m = db.get(ChatMessage, message_id)
            if not m or not can_read_message(db, me, m):
                raise HTTPException(404, "Message not found")
            row = db.get(ChatReaction, (message_id, me.id, data.emoji))
            if row:
                db.delete(row); added = False
            else:
                db.add(ChatReaction(message_id=message_id, user_id=me.id, emoji=data.emoji, created=now())); added = True
            db.commit()
            return {"added": added}

    # ---------------- chat: search ----------------
    @app.get("/api/chat/search")
    def search(q: str = Query(min_length=1, max_length=80), user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            groups = {g.id: g.name for g in db.scalars(select(TeamGroup).join(GroupMember, GroupMember.group_id == TeamGroup.id).where(GroupMember.user_id == me.id))}
            rooms = or_(ChatMessage.room == "main", ChatMessage.room.in_([f"g{g}" for g in groups] or ["-"]),
                        and_(ChatMessage.room == "dm", or_(ChatMessage.sender_id == me.id, ChatMessage.recipient_id == me.id)))
            deleted = select(ChatEdit.message_id).where(ChatEdit.deleted == 1)
            rows = db.scalars(select(ChatMessage).where(rooms, ChatMessage.body.contains(q.strip()), ChatMessage.id.not_in(deleted))
                              .order_by(ChatMessage.id.desc()).limit(50))
            names = {u.id: u.username for u in db.scalars(select(User))}
            out = []
            for m in rows:
                if m.room == "main":
                    room, label = "main", "# 전체 채팅"
                elif m.room == "dm":
                    peer = m.recipient_id if m.sender_id == me.id else m.sender_id
                    room, label = f"u{peer}", f"{names.get(peer, '?')}님과 1:1"
                else:
                    gid = int(m.room[1:]); room, label = f"g{gid}", "# " + groups.get(gid, "그룹")
                out.append({"id": m.id, "room": room, "room_label": label, "sender": m.sender_name, "body": m.body[:200], "created": m.created})
            return out

    # ---------------- chat: pinned notice ----------------
    def may_pin(db, me, m):
        if m.room == "main":
            return me.role == "admin"
        return can_read_message(db, me, m)

    @app.get("/api/chat/pin")
    def get_pin(room: str = Query(max_length=40), user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            if room == "main":
                key = "main"
            elif room.startswith("g") and room[1:].isdigit():
                if not db.get(GroupMember, (int(room[1:]), me.id)):
                    raise HTTPException(404, "Group not found")
                key = room
            elif room.startswith("u") and room[1:].isdigit():
                a, b = sorted([me.id, int(room[1:])]); key = f"dm:{a}-{b}"
            else:
                raise HTTPException(422, "Invalid input")
            pin = db.get(ChatPin, key)
            if not pin:
                return {"pin": None}
            m = db.get(ChatMessage, pin.message_id)
            return {"pin": {"message_id": m.id, "sender": m.sender_name, "body": m.body[:200], "pinned_by": pin.pinned_by, "pinned_at": pin.pinned_at}}

    @app.post("/api/chat/pin")
    def set_pin(data: PinInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            m = db.get(ChatMessage, data.message_id)
            if not m or not can_read_message(db, me, m):
                raise HTTPException(404, "Message not found")
            if not may_pin(db, me, m):
                raise HTTPException(403, "Administrator required")
            key = pin_key(m)
            row = db.get(ChatPin, key)
            if row:
                row.message_id, row.pinned_by, row.pinned_at = m.id, me.username, now()
            else:
                db.add(ChatPin(room_key=key, message_id=m.id, pinned_by=me.username, pinned_at=now()))
            db.commit()
            return {"ok": True}

    @app.delete("/api/chat/pin/{message_id}")
    def clear_pin(message_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            m = db.get(ChatMessage, message_id)
            if not m or not can_read_message(db, me, m):
                raise HTTPException(404, "Message not found")
            if not may_pin(db, me, m):
                raise HTTPException(403, "Administrator required")
            db.execute(delete(ChatPin).where(ChatPin.room_key == pin_key(m)))
            db.commit()
            return {"ok": True}

    # ---------------- kanban tasks ----------------
    from .extras import require_project, visible_project_ids

    def task_json(t):
        return {"id": t.id, "project_id": t.project_id, "title": t.title, "status": t.status, "assignee": t.assignee,
                "due": t.due, "created_by": t.created_by, "updated": t.updated}

    def valid_assignee(db, name):
        if name in (None, ""):
            return None
        if not db.scalar(select(User.id).where(User.username == name)):
            raise HTTPException(404, "User not found")
        return name

    @app.get("/api/tasks")
    def tasks(project_id: Optional[int] = None, user=Depends(authenticated)):
        with Session(engine) as db:
            visible = visible_project_ids(db, user)
            q = select(Task)
            if project_id is not None:
                require_project(db, user, project_id)
                q = q.where(Task.project_id == project_id)
            elif visible is not None:
                q = q.where(Task.project_id.in_(visible or {-1}))
            return [task_json(t) for t in db.scalars(q.order_by(Task.id))]

    @app.get("/api/tasks/due")
    def tasks_due(user=Depends(authenticated)):
        """My open tasks due today or tomorrow (or overdue)."""
        limit = (date.today() + timedelta(days=1)).isoformat()
        with Session(engine) as db:
            visible = visible_project_ids(db, user)
            q = select(Task).where(Task.assignee == user["username"], Task.status != "done", Task.due.is_not(None), Task.due <= limit)
            if visible is not None:
                q = q.where(Task.project_id.in_(visible or {-1}))
            return [task_json(t) for t in db.scalars(q.order_by(Task.due))]

    @app.post("/api/tasks", status_code=201)
    def add_task(data: TaskInput, user=Depends(authenticated)):
        with Session(engine) as db:
            require_project(db, user, data.project_id)
            t = Task(project_id=data.project_id, title=data.title, status="todo", assignee=valid_assignee(db, data.assignee),
                     due=data.due, created_by=user["username"], created=now(), updated=now())
            db.add(t); db.commit()
            return task_json(t)

    @app.patch("/api/tasks/{task_id}")
    def edit_task(task_id: int, data: TaskUpdate, user=Depends(authenticated)):
        with Session(engine) as db:
            t = db.get(Task, task_id)
            if not t:
                raise HTTPException(404, "Task not found")
            require_project(db, user, t.project_id)
            if data.title is not None:
                if not data.title.strip():
                    raise HTTPException(422, "Invalid input")
                t.title = data.title.strip()
            if data.status is not None:
                t.status = data.status
            if data.assignee is not None:
                t.assignee = valid_assignee(db, data.assignee)
            if data.due is not None:
                t.due = data.due or None
            t.updated = now()
            db.commit()
            return task_json(t)

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            t = db.get(Task, task_id)
            if not t:
                raise HTTPException(404, "Task not found")
            require_project(db, user, t.project_id)
            if t.created_by != user["username"] and user["role"] != "admin":
                raise HTTPException(403, "Only the creator or an administrator")
            db.delete(t); db.commit()
            return {"ok": True}

    # ---------------- profiles ----------------
    @app.get("/api/profiles")
    def profiles(user=Depends(authenticated)):
        with Session(engine) as db:
            names = {u.id: u.username for u in db.scalars(select(User))}
            return {names[p.user_id]: {"display_name": p.display_name, "team": p.team, "photo": bool(p.photo_key), "v": p.updated}
                    for p in db.scalars(select(Profile)) if p.user_id in names}

    @app.put("/api/account/profile")
    def set_profile(data: ProfileInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            p = db.get(Profile, me.id)
            if not p:
                p = Profile(user_id=me.id, display_name="", team="", updated=now()); db.add(p)
            p.display_name, p.team, p.updated = data.display_name.strip(), data.team.strip(), now()
            db.commit()
            return {"ok": True}

    @app.post("/api/account/photo")
    def set_photo(file: UploadFile = File(...), user=Depends(authenticated)):
        name = (file.filename or "").lower()
        media = PHOTO_TYPES.get(Path(name).suffix)
        if not media:
            raise HTTPException(415, "Allowed: png, jpg")
        content = file.file.read(512 * 1024 + 1); file.file.close()
        if len(content) > 512 * 1024:
            raise HTTPException(413, "Maximum 512 KiB")
        if not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8")):
            raise HTTPException(415, "Allowed: png, jpg")
        key = "attachments/" + secrets.token_hex(16)
        try:
            storage.put(key, content, media)
        except Exception:
            raise HTTPException(503, "Storage unavailable")
        with Session(engine) as db:
            me = me_row(db, user)
            p = db.get(Profile, me.id)
            if not p:
                p = Profile(user_id=me.id, display_name="", team="", updated=now()); db.add(p)
            old, p.photo_key, p.updated = p.photo_key, key, now()
            db.commit()
        if old:
            storage.discard(old)
        return {"ok": True}

    @app.get("/api/profiles/{username}/photo")
    def photo(username: str, user=Depends(authenticated)):
        with Session(engine) as db:
            u = db.scalar(select(User).where(User.username == username))
            p = db.get(Profile, u.id) if u else None
            if not p or not p.photo_key:
                raise HTTPException(404, "File not found")
            try:
                content = storage.get(p.photo_key, max_bytes=600 * 1024)
            except Exception:
                raise HTTPException(503, "Storage unavailable")
            media = "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
            return Response(content, media_type=media, headers={"Cache-Control": "private, max-age=300"})

    # ---------------- TOTP second factor ----------------
    @app.get("/api/account/totp")
    def totp_state(user=Depends(authenticated)):
        with Session(engine) as db:
            row = db.get(UserTotp, me_row(db, user).id)
            return {"enabled": bool(row and row.enabled)}

    @app.post("/api/account/totp/setup")
    def totp_setup(user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            row = db.get(UserTotp, me.id)
            if row and row.enabled:
                raise HTTPException(409, "Two-factor already enabled")
            secret = totp_new_secret()
            if row:
                row.secret, row.created = secret, now()
            else:
                db.add(UserTotp(user_id=me.id, secret=secret, enabled=0, created=now()))
            db.commit()
            from urllib.parse import quote
            uri = f"otpauth://totp/KOSMOS:{quote(me.username)}?secret={secret}&issuer=KOSMOS&digits=6&period=30"
            return {"secret": secret, "uri": uri}

    @app.post("/api/account/totp/enable")
    def totp_enable(data: CodeInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            row = db.get(UserTotp, me.id)
            if not row:
                raise HTTPException(409, "Start two-factor setup first")
            if not totp_verify(row.secret, data.code):
                raise HTTPException(403, "Invalid code")
            row.enabled = 1
            db.add(Event(kind="security", state="ok", created=now(), summary=f"{me.username}: enabled two-factor login"))
            db.commit()
            return {"enabled": True}

    @app.post("/api/account/totp/disable")
    def totp_disable(data: CodeInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            row = db.get(UserTotp, me.id)
            if not row or not row.enabled:
                raise HTTPException(409, "Two-factor not enabled")
            if not totp_verify(row.secret, data.code):
                raise HTTPException(403, "Invalid code")
            db.delete(row)
            db.add(Event(kind="security", state="ok", created=now(), summary=f"{me.username}: disabled two-factor login"))
            db.commit()
            return {"enabled": False}

    @app.delete("/api/admin/users/{user_id}/totp")
    def totp_reset(user_id: int, actor=Depends(admin)):
        """Recovery for a member who lost their phone (admin only)."""
        with Session(engine) as db:
            target = db.get(User, user_id)
            if not target:
                raise HTTPException(404, "User not found")
            db.execute(delete(UserTotp).where(UserTotp.user_id == user_id))
            db.add(Event(kind="security", state="ok", created=now(), summary=f"{actor['username']}: reset two-factor of {target.username}"))
            db.commit()
            return {"ok": True}
