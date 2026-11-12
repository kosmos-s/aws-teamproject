"""Live change detection and team chat (main room + 1:1).

Polling-based on purpose: works through the existing Nginx config with no
long-lived connections, and each poll is a handful of indexed MAX/COUNT queries.
"""
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session

from .models import (User, BlockedUser, LoginSession, Project, Note, Attachment, Event,
                     ChatMessage, ChatRead, TeamGroup, GroupMember, NoteEdit, ProjectArchive, ChatEdit,
                     AttachmentOwner, ProjectAccess)

MAX_PAGE = 200


class ChatInput(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank message")
        return value.strip()


def install_collab_routes(app, authenticated):
    engine = app.state.engine
    recent_posts = {}

    def me_row(db, user):
        row = db.scalar(select(User).where(User.username == user["username"]))
        if not row:
            raise HTTPException(401, "Login required")
        return row

    def throttle(user_id):
        # 20 messages per 10 seconds per user is plenty for people, stops runaway scripts.
        now = time.time()
        recent = [t for t in recent_posts.get(user_id, []) if now - t < 10]
        if len(recent) >= 20:
            raise HTTPException(429, "Too many messages")
        recent_posts[user_id] = recent + [now]

    def max_id(db, column, *where):
        return db.scalar(select(func.max(column)).where(*where)) or 0

    def last_read(db, user_id, key):
        row = db.get(ChatRead, (user_id, key))
        return row.last_id if row else 0

    def mark_read(db, user_id, key, last_id):
        row = db.get(ChatRead, (user_id, key))
        if row is None:
            db.add(ChatRead(user_id=user_id, room_key=key, last_id=last_id))
        elif last_id > row.last_id:
            row.last_id = last_id
        else:
            return
        app.state.change_version = getattr(app.state, "change_version", 0) + 1

    def dm_filter(a, b):
        return and_(ChatMessage.room == "dm", or_(and_(ChatMessage.sender_id == a, ChatMessage.recipient_id == b),
                                                  and_(ChatMessage.sender_id == b, ChatMessage.recipient_id == a)))

    def unread_main(db, uid):
        return db.scalar(select(func.count(ChatMessage.id)).where(
            ChatMessage.room == "main", ChatMessage.id > last_read(db, uid, "main"),
            or_(ChatMessage.sender_id != uid, ChatMessage.sender_id.is_(None)))) or 0

    def unread_dm(db, uid, peer):
        return db.scalar(select(func.count(ChatMessage.id)).where(
            ChatMessage.room == "dm", ChatMessage.sender_id == peer, ChatMessage.recipient_id == uid,
            ChatMessage.id > last_read(db, uid, f"dm:{peer}"))) or 0

    def unread_group(db, uid, gid):
        return db.scalar(select(func.count(ChatMessage.id)).where(
            ChatMessage.room == f"g{gid}", ChatMessage.id > last_read(db, uid, f"g:{gid}"),
            or_(ChatMessage.sender_id != uid, ChatMessage.sender_id.is_(None)))) or 0

    def member_group_or_404(db, gid, me):
        if not db.get(TeamGroup, gid) or not db.get(GroupMember, (gid, me.id)):
            raise HTTPException(404, "Group not found")

    def serialize(m, uid, edits=None, readers=None):
        e = (edits or {}).get(m.id)
        unread_by = 0
        if readers is not None:
            unread_by = sum(1 for pid, last in readers.items() if pid != m.sender_id and last < m.id)
        return {"id": m.id, "sender": m.sender_name, "mine": m.sender_id == uid, "body": m.body, "created": m.created,
                "edited": e.edited_at if e and not e.deleted else None, "deleted": bool(e and e.deleted),
                "unread_by": unread_by}

    def room_readers(db, participants, key_for):
        """participant user_id -> last read message id in this room."""
        reads = {}
        for pid in participants:
            r = db.get(ChatRead, (pid, key_for(pid)))
            reads[pid] = r.last_id if r else 0
        return reads

    def with_edits(db, rows):
        ids = [m.id for m in rows]
        return {e.message_id: e for e in db.scalars(select(ChatEdit).where(ChatEdit.message_id.in_(ids)))} if ids else {}

    @app.get("/api/changes")
    def changes(user=Depends(authenticated)):
        """Cheap fingerprint the browser polls; it reloads a section only when this changes."""
        with Session(engine) as db:
            uid = me_row(db, user).id
            board = "-".join(str(x) for x in (
                max_id(db, Project.id), max_id(db, Note.id), max_id(db, Attachment.id),
                db.scalar(select(func.count(Project.id))) or 0, db.scalar(select(func.count(Attachment.id))) or 0,
                db.scalar(select(func.count(Note.id))) or 0, db.scalar(select(func.max(NoteEdit.edited_at))) or "",
                db.scalar(select(func.count(ProjectArchive.project_id))) or 0,
                db.scalar(select(func.count(AttachmentOwner.attachment_id))) or 0))
            dm_unread = db.scalar(select(func.count(ChatMessage.id)).where(
                ChatMessage.room == "dm", ChatMessage.recipient_id == uid)) or 0
            return {"board": board, "events": max_id(db, Event.id),
                    "chat": f"{max_id(db, ChatMessage.id)}|{dm_unread}|{db.scalar(select(func.max(ChatEdit.edited_at))) or ''}|{db.scalar(select(func.sum(ChatRead.last_id))) or 0}",
                    "access": f"{db.scalar(select(func.count(ProjectAccess.project_id))) or 0}-{db.scalar(select(func.count(GroupMember.user_id))) or 0}",
                    "users": db.scalar(select(func.count(User.id))) or 0}

    @app.get("/api/chat/people")
    def people(user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            online = set(db.scalars(select(LoginSession.user_id).where(LoginSession.expires > time.time())))
            out = []
            for u in db.scalars(select(User).order_by(User.username)):
                if u.id == me.id or u.id in blocked:
                    continue
                out.append({"id": u.id, "username": u.username, "role": u.role, "online": u.id in online,
                            "unread": unread_dm(db, me.id, u.id)})
            groups = []
            for g in db.scalars(select(TeamGroup).join(GroupMember, GroupMember.group_id == TeamGroup.id)
                                .where(GroupMember.user_id == me.id).order_by(TeamGroup.name)):
                n = db.scalar(select(func.count(GroupMember.user_id)).where(GroupMember.group_id == g.id)) or 0
                groups.append({"id": g.id, "name": g.name, "members": n, "unread": unread_group(db, me.id, g.id)})
            return {"main_unread": unread_main(db, me.id), "people": out, "groups": groups}

    @app.get("/api/chat/main")
    def main_messages(after: int = Query(0, ge=0), user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            q = select(ChatMessage).where(ChatMessage.room == "main", ChatMessage.id > after)
            rows = list(db.scalars(q.order_by(ChatMessage.id.desc()).limit(MAX_PAGE)))[::-1]
            if rows:
                mark_read(db, me.id, "main", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            people = [u for u in db.scalars(select(User.id)) if u not in blocked]
            readers = room_readers(db, people, lambda pid: "main")
            return [serialize(m, me.id, edits, readers) for m in rows]

    @app.post("/api/chat/main", status_code=201)
    def post_main(data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            throttle(me.id)
            m = ChatMessage(room="main", sender_id=me.id, sender_name=me.username, body=data.body,
                            created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            mark_read(db, me.id, "main", m.id)
            db.commit()
            return serialize(m, me.id)

    @app.get("/api/chat/group/{gid}")
    def group_messages(gid: int, after: int = Query(0, ge=0), user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            member_group_or_404(db, gid, me)
            q = select(ChatMessage).where(ChatMessage.room == f"g{gid}", ChatMessage.id > after)
            rows = list(db.scalars(q.order_by(ChatMessage.id.desc()).limit(MAX_PAGE)))[::-1]
            if rows:
                mark_read(db, me.id, f"g:{gid}", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            members = list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == gid)))
            readers = room_readers(db, members, lambda pid: f"g:{gid}")
            return [serialize(m, me.id, edits, readers) for m in rows]

    @app.post("/api/chat/group/{gid}", status_code=201)
    def post_group(gid: int, data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            member_group_or_404(db, gid, me)
            throttle(me.id)
            m = ChatMessage(room=f"g{gid}", sender_id=me.id, sender_name=me.username, body=data.body,
                            created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            mark_read(db, me.id, f"g:{gid}", m.id)
            db.commit()
            return serialize(m, me.id)

    def peer_or_404(db, peer_id, me):
        peer = db.get(User, peer_id)
        if not peer or peer.id == me.id:
            raise HTTPException(404, "User not found")
        return peer

    @app.get("/api/chat/dm/{peer_id}")
    def dm_messages(peer_id: int, after: int = Query(0, ge=0), user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            peer_or_404(db, peer_id, me)
            q = select(ChatMessage).where(dm_filter(me.id, peer_id), ChatMessage.id > after)
            rows = list(db.scalars(q.order_by(ChatMessage.id.desc()).limit(MAX_PAGE)))[::-1]
            if rows:
                mark_read(db, me.id, f"dm:{peer_id}", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            readers = room_readers(db, [me.id, peer_id], lambda pid: f"dm:{peer_id if pid == me.id else me.id}")
            return [serialize(m, me.id, edits, readers) for m in rows]

    @app.post("/api/chat/dm/{peer_id}", status_code=201)
    def post_dm(peer_id: int, data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            peer = peer_or_404(db, peer_id, me)
            if db.get(BlockedUser, peer.id):
                raise HTTPException(409, "Recipient is blocked")
            throttle(me.id)
            m = ChatMessage(room="dm", sender_id=me.id, sender_name=me.username, recipient_id=peer.id,
                            body=data.body, created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            mark_read(db, me.id, f"dm:{peer.id}", m.id)
            db.commit()
            return serialize(m, me.id)


def forget_user_chat(db, user_id):
    """Called before deleting an account: drop its 1:1 chats and read marks, keep its main-room
    messages under the stored name so the team's history stays readable."""
    from sqlalchemy import delete, update
    dm_ids = list(db.scalars(select(ChatMessage.id).where(ChatMessage.room == "dm",
                  or_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == user_id))))
    if dm_ids:
        db.execute(delete(ChatEdit).where(ChatEdit.message_id.in_(dm_ids)))
    db.execute(delete(ChatMessage).where(ChatMessage.room == "dm",
                                         or_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == user_id)))
    db.execute(update(ChatMessage).where(ChatMessage.sender_id == user_id).values(sender_id=None))
    db.execute(delete(ChatRead).where(ChatRead.user_id == user_id))
    db.execute(delete(ChatRead).where(ChatRead.room_key == f"dm:{user_id}"))
