"""Club/company features: groups (+ group chat), note edit/delete, project archive,
bulk invites, last login and forced first-login password change."""
import re
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (User, Note, NoteEdit, Project, ProjectArchive, TeamGroup, GroupMember, UserActivity,
                     ChatMessage, ChatRead, Event)
from .security import create_user

USERNAME = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


def now():
    return datetime.now(timezone.utc).isoformat()


def activity(db, user_id):
    row = db.get(UserActivity, user_id)
    if row is None:
        row = UserActivity(user_id=user_id, must_change=0)
        db.add(row)
    return row


def set_must_change(db, user_id, value):
    activity(db, user_id).must_change = 1 if value else 0


def must_change(db, user_id):
    row = db.get(UserActivity, user_id)
    return bool(row and row.must_change)


def forget_user_teamwork(db, user_id):
    db.execute(delete(GroupMember).where(GroupMember.user_id == user_id))
    db.execute(delete(UserActivity).where(UserActivity.user_id == user_id))


def user_groups(db, user_id):
    q = select(TeamGroup).join(GroupMember, GroupMember.group_id == TeamGroup.id).where(GroupMember.user_id == user_id)
    return list(db.scalars(q.order_by(TeamGroup.name)))


class NoteUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank note")
        return value.strip()


class GroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank name")
        return value.strip()


class GroupMembers(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=1000)


class BulkInvite(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    default_role: Literal["member", "viewer"] = "member"


def install_teamwork_routes(app, authenticated, admin):
    engine = app.state.engine

    def audit(db, actor, kind, summary):
        db.add(Event(kind=kind, state="ok", created=now(), summary=f"{actor}: {summary}"))

    # ---- work notes: author or admin may edit/delete -------------------------------
    def editable_note(db, note_id, user):
        note = db.get(Note, note_id)
        if not note:
            raise HTTPException(404, "Note not found")
        if note.author != user["username"] and user["role"] != "admin":
            raise HTTPException(403, "Only the author or an administrator")
        return note

    @app.patch("/api/notes/{note_id}")
    def edit_note(note_id: int, data: NoteUpdate, user=Depends(authenticated)):
        with Session(engine) as db:
            note = editable_note(db, note_id, user)
            note.body = data.body
            edit = db.get(NoteEdit, note_id)
            if edit:
                edit.edited_by, edit.edited_at = user["username"], now()
            else:
                db.add(NoteEdit(note_id=note_id, edited_by=user["username"], edited_at=now()))
            db.commit()
            return {"ok": True}

    @app.delete("/api/notes/{note_id}")
    def delete_note(note_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            note = editable_note(db, note_id, user)
            db.execute(delete(NoteEdit).where(NoteEdit.note_id == note_id))
            db.delete(note)
            if note.author != user["username"]:
                audit(db, user["username"], "content", f"deleted note {note_id} by {note.author}")
            db.commit()
            return {"ok": True}

    # ---- project archive (admin) ----------------------------------------------------
    @app.post("/api/projects/{project_id}/archive")
    def archive(project_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            if not db.get(Project, project_id):
                raise HTTPException(404, "Project not found")
            if not db.get(ProjectArchive, project_id):
                db.add(ProjectArchive(project_id=project_id, archived_by=actor["username"], archived_at=now()))
                audit(db, actor["username"], "content", f"archived project {project_id}")
            db.commit()
            return {"ok": True}

    @app.delete("/api/projects/{project_id}/archive")
    def unarchive(project_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            if not db.get(ProjectArchive, project_id):
                raise HTTPException(404, "Project not archived")
            db.execute(delete(ProjectArchive).where(ProjectArchive.project_id == project_id))
            audit(db, actor["username"], "content", f"restored project {project_id}")
            db.commit()
            return {"ok": True}

    # ---- groups (admin manages, members chat) ---------------------------------------
    @app.get("/api/admin/groups")
    def groups(actor=Depends(admin)):
        with Session(engine) as db:
            members = {}
            for gm in db.scalars(select(GroupMember)):
                members.setdefault(gm.group_id, []).append(gm.user_id)
            return [{"id": g.id, "name": g.name, "description": g.description, "user_ids": sorted(members.get(g.id, []))}
                    for g in db.scalars(select(TeamGroup).order_by(TeamGroup.name))]

    @app.post("/api/admin/groups", status_code=201)
    def create_group(data: GroupInput, actor=Depends(admin)):
        with Session(engine) as db:
            g = TeamGroup(name=data.name, description=data.description.strip(), created=now())
            db.add(g)
            try:
                db.flush()
            except IntegrityError:
                raise HTTPException(409, "Group already exists")
            audit(db, actor["username"], "account-access", f"created group {data.name}")
            db.commit()
            return {"id": g.id, "name": g.name}

    @app.put("/api/admin/groups/{group_id}/members")
    def set_members(group_id: int, data: GroupMembers, actor=Depends(admin)):
        with Session(engine) as db:
            g = db.get(TeamGroup, group_id)
            if not g:
                raise HTTPException(404, "Group not found")
            valid = set(db.scalars(select(User.id).where(User.id.in_(data.user_ids)))) if data.user_ids else set()
            if valid != set(data.user_ids):
                raise HTTPException(404, "User not found")
            db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))
            for uid in sorted(valid):
                db.add(GroupMember(group_id=group_id, user_id=uid))
            audit(db, actor["username"], "account-access", f"group {g.name}: {len(valid)} members")
            db.commit()
            return {"ok": True, "members": len(valid)}

    @app.delete("/api/admin/groups/{group_id}")
    def delete_group(group_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            g = db.get(TeamGroup, group_id)
            if not g:
                raise HTTPException(404, "Group not found")
            name = g.name
            db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))
            db.execute(delete(ChatMessage).where(ChatMessage.room == f"g{group_id}"))
            db.execute(delete(ChatRead).where(ChatRead.room_key == f"g:{group_id}"))
            db.delete(g)
            audit(db, actor["username"], "account-access", f"deleted group {name} and its chat")
            db.commit()
            return {"ok": True}

    # ---- bulk invite (admin) --------------------------------------------------------
    @app.post("/api/admin/users/bulk")
    def bulk_invite(data: BulkInvite, actor=Depends(admin)):
        lines = [l.strip() for l in data.text.splitlines() if l.strip() and not l.strip().startswith("#")]
        if len(lines) > 200:
            raise HTTPException(413, "At most 200 accounts per batch")
        results = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            name = parts[0]
            role = (parts[1] if len(parts) > 1 and parts[1] else data.default_role).lower()
            group = parts[2] if len(parts) > 2 else ""
            if not USERNAME.fullmatch(name):
                results.append({"username": name[:80], "error": "아이디 형식 오류"}); continue
            if role not in {"admin", "member", "viewer"}:
                results.append({"username": name, "error": "역할 오류 (admin/member/viewer)"}); continue
            if len(group) > 80:
                results.append({"username": name, "error": "그룹 이름이 너무 깁니다"}); continue
            password = secrets.token_urlsafe(9)[:12]
            try:
                create_user(engine, name, password, role)
            except IntegrityError:
                results.append({"username": name, "error": "이미 있는 아이디"}); continue
            with Session(engine) as db:
                uid = db.scalar(select(User.id).where(User.username == name))
                set_must_change(db, uid, True)
                if group:
                    g = db.scalar(select(TeamGroup).where(TeamGroup.name == group))
                    if not g:
                        g = TeamGroup(name=group, description="", created=now()); db.add(g); db.flush()
                    db.add(GroupMember(group_id=g.id, user_id=uid))
                db.commit()
            results.append({"username": name, "role": role, "group": group, "password": password})
        with Session(engine) as db:
            ok = sum(1 for r in results if "password" in r)
            audit(db, actor["username"], "account-access", f"bulk invite {ok}/{len(results)} created")
            db.commit()
        return {"created": sum(1 for r in results if "password" in r), "results": results}
