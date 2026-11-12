"""Audience-scoped long polling for the explicitly single-worker deployment."""

import asyncio
import threading
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import ChatMessage, GroupMember, User


class ChangeHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.global_versions = defaultdict(int)
        self.user_versions = defaultdict(lambda: defaultdict(int))
        self.waiters = {}

    def snapshot(self, uid):
        with self.lock:
            return {
                k: max(self.global_versions[k], self.user_versions[uid][k])
                for k in ("board", "chat", "reads", "access", "users", "typing")
            }

    def version(self, uid):
        return max(self.snapshot(uid).values(), default=0)

    def publish(self, section, audience=None):
        with self.lock:
            self.seq += 1
            if audience is None:
                self.global_versions[section] = self.seq
            else:
                for uid in audience:
                    self.user_versions[uid][section] = self.seq
            for uid, entries in list(self.waiters.items()):
                if audience is None or uid in audience:
                    for event, loop in tuple(entries):
                        try:
                            loop.call_soon_threadsafe(event.set)
                        except RuntimeError:
                            pass

    async def wait(self, uid, version):
        if self.version(uid) != version:
            return
        event = asyncio.Event()
        entry = (event, asyncio.get_running_loop())
        with self.lock:
            self.waiters.setdefault(uid, set()).add(entry)
        try:
            if self.version(uid) == version:
                try:
                    await asyncio.wait_for(event.wait(), 25)
                except asyncio.TimeoutError:
                    pass
        finally:
            with self.lock:
                self.waiters[uid].discard(entry)
                if not self.waiters[uid]:
                    self.waiters.pop(uid, None)


def room_audience(db, m):
    if m.room == "main":
        return None
    if m.room == "dm":
        return {u for u in (m.sender_id, m.recipient_id) if u is not None}
    if m.room.startswith("g") and m.room[1:].isdigit():
        return set(
            db.scalars(
                select(GroupMember.user_id).where(
                    GroupMember.group_id == int(m.room[1:])
                )
            )
        )
    return set()


def publish_write(app, path, uid=None, typing_room=None):
    if path in {"/api/login", "/api/logout", "/api/activity", "/api/chat/read"}:
        return
    hub = app.state.changes
    if path.startswith("/api/chat/"):
        bits = path.split("/")
        with Session(app.state.engine) as db:
            if typing_room:
                if typing_room == "main":
                    audience = None
                elif typing_room.startswith("g"):
                    audience = set(
                        db.scalars(
                            select(GroupMember.user_id).where(
                                GroupMember.group_id == int(typing_room[1:])
                            )
                        )
                    )
                else:
                    audience = {uid, int(typing_room[1:])}
            elif (
                len(bits) > 4 and bits[3] in {"messages", "files"} and bits[4].isdigit()
            ):
                m = db.get(ChatMessage, int(bits[4]))
                audience = room_audience(db, m) if m else {uid}
            elif len(bits) > 4 and bits[3] in {"group", "dm"} and bits[4].isdigit():
                audience = (
                    set(
                        db.scalars(
                            select(GroupMember.user_id).where(
                                GroupMember.group_id == int(bits[4])
                            )
                        )
                    )
                    if bits[3] == "group"
                    else {uid, int(bits[4])}
                )
            elif bits[3] == "main":
                audience = None
            else:
                audience = {uid}
        hub.publish("typing" if typing_room else "chat", audience)
    elif "/groups" in path or "/access" in path:
        hub.publish("access")
        hub.publish("board")
        hub.publish("chat")
    elif "/users" in path or "/profile" in path:
        hub.publish("users")
    elif path.startswith("/api/account/"):
        return
    else:
        hub.publish("board")
