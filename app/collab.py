"""Live change detection and team chat (main room + 1:1).

Polling-based on purpose: works through the existing Nginx config with no
long-lived connections, and each poll is a handful of indexed MAX/COUNT queries.
"""
import time
from datetime import datetime, timezone

from typing import Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, or_, and_, cast, String, case
from sqlalchemy.orm import Session

from .models import (User, BlockedUser, LoginSession, Project, Note, Attachment, Event,
                     ChatMessage, ChatRead, TeamGroup, GroupMember, NoteEdit, ProjectArchive, ChatEdit,
                     AttachmentOwner, ProjectAccess, ChatReaction, ChatPin, ChatReply, Task, Profile)
from .suite import extras_for, extra_fields, purge_messages

MAX_PAGE = 200


class TypingInput(BaseModel):
    room: str = Field(max_length=20, pattern=r"^(main|g\d{1,9}|u\d{1,9})$")


class ReadInput(TypingInput):
    last_id: int = Field(ge=0)


class ChatInput(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    reply_to: Optional[int] = None

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

    from .antispam import AntiSpam
    app.state.antispam = getattr(app.state, "antispam", None) or AntiSpam()

    def throttle(user_id, text=""):
        app.state.antispam.check(user_id, text)

    # "OO님이 입력 중…": in-memory, single worker. canonical key -> {user_id: (name, ts)}
    typing = {}
    TYPING_TTL = 6

    def canonical_room(db, me, room):
        if room == "main":
            return "main"
        if room.startswith("g"):
            gid = int(room[1:])
            if not db.get(GroupMember, (gid, me.id)):
                raise HTTPException(404, "Group not found")
            return room
        peer = int(room[1:])
        if not db.get(User, peer) or peer == me.id:
            raise HTTPException(404, "User not found")
        a, b = sorted([me.id, peer])
        return f"dm:{a}-{b}"

    def typing_for(db, me):
        """Active typers in rooms I can see, keyed by MY room key ('main', 'g<id>', 'u<peer>')."""
        now_t = time.time(); out = []
        my_groups = None
        for key, people in list(typing.items()):
            for uid, (name, ts) in list(people.items()):
                if now_t - ts > TYPING_TTL:
                    people.pop(uid, None); continue
                if uid == me.id:
                    continue
                if key == "main":
                    out.append({"room": "main", "name": name})
                elif key.startswith("g"):
                    if my_groups is None:
                        my_groups = set(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == me.id)))
                    if int(key[1:]) in my_groups:
                        out.append({"room": key, "name": name})
                else:
                    a, b = (int(x) for x in key[3:].split("-"))
                    if me.id in (a, b):
                        out.append({"room": f"u{uid}", "name": name})
            if not people:
                typing.pop(key, None)
        return out

    @app.post("/api/chat/typing")
    def chat_typing(data: TypingInput, request: Request, user=Depends(authenticated)):
        request.state.typing_room = data.room
        with Session(engine) as db:
            me = me_row(db, user)
            key = canonical_room(db, me, data.room)
            typing.setdefault(key, {})[me.id] = (me.username, time.time())
            return {"ok": True}

    def max_id(db, column, *where):
        return db.scalar(select(func.max(column)).where(*where)) or 0

    def last_read(db, user_id, key):
        row = db.get(ChatRead, (user_id, key))
        return row.last_id if row else 0

    def mark_read(db, user_id, key, last_id):
        if last_id <= last_read(db,user_id,key): return
        from .db_atomic import mark_read as atomic_mark
        atomic_mark(db,user_id,key,last_id)
        if key=='main': audience=None
        elif key.startswith('g:'):
            audience=set(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id==int(key[2:]))))
        else: audience={user_id,int(key[3:])}
        app.state.changes.publish('reads',audience)

    def dm_filter(a, b):
        return and_(ChatMessage.room == "dm", or_(and_(ChatMessage.sender_id == a, ChatMessage.recipient_id == b),
                                                  and_(ChatMessage.sender_id == b, ChatMessage.recipient_id == a)))

    @app.post('/api/chat/read')
    def acknowledge(data:ReadInput,user=Depends(authenticated)):
        with Session(engine) as db:
            me=me_row(db,user)
            canonical_room(db,me,data.room)
            if data.last_id:
                m=db.get(ChatMessage,data.last_id)
                from .suite import can_read_message
                if not m or not can_read_message(db,me,m) or (data.room.startswith('u') and (m.room!='dm' or {m.sender_id,m.recipient_id}!={me.id,int(data.room[1:])})) or (not data.room.startswith('u') and m.room!=data.room):
                    raise HTTPException(404,'Message not found')
            key='main' if data.room=='main' else (f'g:{data.room[1:]}' if data.room.startswith('g') else f'dm:{data.room[1:]}')
            mark_read(db,me.id,key,data.last_id);db.commit()
        return {'ok':True}

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

    def attach_reply(db, m, reply_to):
        if not reply_to:
            return
        q = db.get(ChatMessage, reply_to)
        same = q is not None and q.room == m.room and (m.room != "dm" or {q.sender_id, q.recipient_id} == {m.sender_id, m.recipient_id})
        if not same:
            raise HTTPException(404, "Message not found")
        db.add(ChatReply(message_id=m.id, reply_to=reply_to))

    def serialize(m, uid, edits=None, readers=None, extras=None):
        e = (edits or {}).get(m.id)
        unread_by = 0
        if readers is not None:
            unread_by = sum(1 for pid, last in readers.items() if pid != m.sender_id and last < m.id)
        return {"id": m.id, "sender": m.sender_name, "mine": m.sender_id == uid, "body": m.body, "created": m.created,
                "edited": e.edited_at if e and not e.deleted else None, "deleted": bool(e and e.deleted),
                "unread_by": unread_by, **extra_fields(m, uid, extras)}

    def room_readers(db, participants, key_for):
        """participant user_id -> last read message id in this room."""
        participants=list(participants)
        keys={key_for(pid) for pid in participants}
        found={(r.user_id,r.room_key):r.last_id for r in db.scalars(select(ChatRead).where(ChatRead.user_id.in_(participants),ChatRead.room_key.in_(keys)))} if participants else {}
        return {pid:found.get((pid,key_for(pid)),0) for pid in participants}

    def with_edits(db, rows):
        ids = [m.id for m in rows]
        return {e.message_id: e for e in db.scalars(select(ChatEdit).where(ChatEdit.message_id.in_(ids)))} if ids else {}

    @app.get("/api/changes")
    def changes(user=Depends(authenticated)):
        """Cheap fingerprint the browser polls; it reloads a section only when this changes."""
        with Session(engine) as db:
            versions=app.state.changes.snapshot(user['id'])
            return {'board':str(versions['board']),'events':max_id(db,Event.id),
                    'chat':f"{versions['chat']}|0|{versions['reads']}",
                    'access':str(versions['access']),'users':str(versions['users']),
                    'typing':typing_for(db,me_row(db,user))}

    @app.get("/api/chat/people")
    def people(user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            online = set(db.scalars(select(LoginSession.user_id).where(LoginSession.expires > time.time())))
            dm_read=ChatRead.__table__.alias('dm_read')
            dm_counts=dict(db.execute(select(ChatMessage.sender_id,func.count(ChatMessage.id)).outerjoin(dm_read,
                and_(dm_read.c.user_id==me.id,dm_read.c.room_key==('dm:'+cast(ChatMessage.sender_id,String)))).where(
                ChatMessage.room=='dm',ChatMessage.recipient_id==me.id,ChatMessage.id>func.coalesce(dm_read.c.last_id,0)).group_by(ChatMessage.sender_id)).all())
            group_read=ChatRead.__table__.alias('group_read')
            group_counts=dict(db.execute(select(ChatMessage.room,func.count(ChatMessage.id)).outerjoin(group_read,
                and_(group_read.c.user_id==me.id,group_read.c.room_key==('g:'+func.substr(ChatMessage.room,2)))).where(
                ChatMessage.room.like('g%'),ChatMessage.id>func.coalesce(group_read.c.last_id,0),
                or_(ChatMessage.sender_id!=me.id,ChatMessage.sender_id.is_(None))).group_by(ChatMessage.room)).all())
            member_counts=dict(db.execute(select(GroupMember.group_id,func.count(GroupMember.user_id)).group_by(GroupMember.group_id)).all())
            out = []
            for u in db.scalars(select(User).order_by(User.username)):
                if u.id == me.id or u.id in blocked:
                    continue
                out.append({"id": u.id, "username": u.username, "role": u.role, "online": u.id in online,
                            "unread": dm_counts.get(u.id,0)})
            groups = []
            for g in db.scalars(select(TeamGroup).join(GroupMember, GroupMember.group_id == TeamGroup.id)
                                .where(GroupMember.user_id == me.id).order_by(TeamGroup.name)):
                n = member_counts.get(g.id,0)
                groups.append({"id": g.id, "name": g.name, "members": n, "unread": group_counts.get(f"g{g.id}",0)})
            mr=ChatRead.__table__.alias('mention_read')
            key=case((ChatMessage.room=='main','main'),
                (ChatMessage.room=='dm','dm:'+cast(ChatMessage.sender_id,String)),else_='g:'+func.substr(ChatMessage.room,2))
            visible=or_(ChatMessage.room=='main',and_(ChatMessage.room=='dm',ChatMessage.recipient_id==me.id),
                ChatMessage.room.in_(select('g'+cast(GroupMember.group_id,String)).where(GroupMember.user_id==me.id)))
            candidates=db.scalars(select(ChatMessage.body).outerjoin(mr,and_(mr.c.user_id==me.id,mr.c.room_key==key)).where(
                visible,ChatMessage.id>func.coalesce(mr.c.last_id,0),ChatMessage.sender_id!=me.id,
                ChatMessage.id.not_in(select(ChatEdit.message_id).where(ChatEdit.deleted==1)),ChatMessage.body.contains('@'+me.username)))
            import re
            mention_unread=sum(bool(re.search(r'(?<![\w@])@'+re.escape(me.username)+r'(?![\w.\-])',body)) for body in candidates)
            return {"main_unread": unread_main(db, me.id), "people": out, "groups": groups, "mention_unread":mention_unread}

    @app.get("/api/chat/main")
    def main_messages(after: int = Query(0, ge=0), before: int = Query(0, ge=0), read: bool = True, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            q = select(ChatMessage).where(ChatMessage.room == "main", ChatMessage.id > after)
            if before: q=q.where(ChatMessage.id < before)
            rows = list(db.scalars(q.order_by(ChatMessage.id.asc() if after and not before else ChatMessage.id.desc()).limit(MAX_PAGE)))
            if not after or before: rows.reverse()
            if rows and read and not before:
                mark_read(db, me.id, "main", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            extras = extras_for(db, rows)
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            people = [u for u in db.scalars(select(User.id)) if u not in blocked]
            readers = room_readers(db, people, lambda pid: "main")
            return [serialize(m, me.id, edits, readers, extras) for m in rows]

    @app.post("/api/chat/main", status_code=201)
    def post_main(data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            throttle(me.id, data.body)
            m = ChatMessage(room="main", sender_id=me.id, sender_name=me.username, body=data.body,
                            created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            attach_reply(db, m, data.reply_to)
            mark_read(db, me.id, "main", m.id)
            db.commit()
            return serialize(m, me.id)

    @app.get("/api/chat/group/{gid}")
    def group_messages(gid: int, after: int = Query(0, ge=0), before: int = Query(0, ge=0), read: bool = True, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            member_group_or_404(db, gid, me)
            q = select(ChatMessage).where(ChatMessage.room == f"g{gid}", ChatMessage.id > after)
            if before: q=q.where(ChatMessage.id < before)
            rows = list(db.scalars(q.order_by(ChatMessage.id.asc() if after and not before else ChatMessage.id.desc()).limit(MAX_PAGE)))
            if not after or before: rows.reverse()
            if rows and read and not before:
                mark_read(db, me.id, f"g:{gid}", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            extras = extras_for(db, rows)
            members = list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == gid)))
            readers = room_readers(db, members, lambda pid: f"g:{gid}")
            return [serialize(m, me.id, edits, readers, extras) for m in rows]

    @app.post("/api/chat/group/{gid}", status_code=201)
    def post_group(gid: int, data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            member_group_or_404(db, gid, me)
            throttle(me.id, data.body)
            m = ChatMessage(room=f"g{gid}", sender_id=me.id, sender_name=me.username, body=data.body,
                            created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            attach_reply(db, m, data.reply_to)
            mark_read(db, me.id, f"g:{gid}", m.id)
            db.commit()
            return serialize(m, me.id)

    def peer_or_404(db, peer_id, me):
        peer = db.get(User, peer_id)
        if not peer or peer.id == me.id:
            raise HTTPException(404, "User not found")
        return peer

    @app.get("/api/chat/dm/{peer_id}")
    def dm_messages(peer_id: int, after: int = Query(0, ge=0), before: int = Query(0, ge=0), read: bool = True, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            peer_or_404(db, peer_id, me)
            q = select(ChatMessage).where(dm_filter(me.id, peer_id), ChatMessage.id > after)
            if before: q=q.where(ChatMessage.id < before)
            rows = list(db.scalars(q.order_by(ChatMessage.id.asc() if after and not before else ChatMessage.id.desc()).limit(MAX_PAGE)))
            if not after or before: rows.reverse()
            if rows and read and not before:
                mark_read(db, me.id, f"dm:{peer_id}", rows[-1].id)
                db.commit()
            edits = with_edits(db, rows)
            extras = extras_for(db, rows)
            readers = room_readers(db, [me.id, peer_id], lambda pid: f"dm:{peer_id if pid == me.id else me.id}")
            return [serialize(m, me.id, edits, readers, extras) for m in rows]

    @app.post("/api/chat/dm/{peer_id}", status_code=201)
    def post_dm(peer_id: int, data: ChatInput, user=Depends(authenticated)):
        with Session(engine) as db:
            me = me_row(db, user)
            peer = peer_or_404(db, peer_id, me)
            if db.get(BlockedUser, peer.id):
                raise HTTPException(409, "Recipient is blocked")
            throttle(me.id, data.body)
            m = ChatMessage(room="dm", sender_id=me.id, sender_name=me.username, recipient_id=peer.id,
                            body=data.body, created=datetime.now(timezone.utc).isoformat())
            db.add(m)
            db.flush()
            attach_reply(db, m, data.reply_to)
            mark_read(db, me.id, f"dm:{peer.id}", m.id)
            db.commit()
            return serialize(m, me.id)


def forget_user_chat(db, user_id):
    """Called before deleting an account: drop its 1:1 chats and read marks, keep its main-room
    messages under the stored name so the team's history stays readable."""
    from sqlalchemy import delete, update
    dm_ids = list(db.scalars(select(ChatMessage.id).where(ChatMessage.room == "dm",
                  or_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == user_id))))
    purge_messages(db, dm_ids)
    db.execute(delete(ChatMessage).where(ChatMessage.room == "dm",
                                         or_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == user_id)))
    db.execute(update(ChatMessage).where(ChatMessage.sender_id == user_id).values(sender_id=None))
    db.execute(delete(ChatRead).where(ChatRead.user_id == user_id))
    db.execute(delete(ChatRead).where(ChatRead.room_key == f"dm:{user_id}"))
