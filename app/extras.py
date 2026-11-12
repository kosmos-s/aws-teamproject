"""2026-11-12: attachment delete, chat edit/delete, project access by group, activity log."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session

from .models import (Attachment, AttachmentOwner, ChatMessage, ChatEdit, Event, GroupMember, Project,
                     ProjectAccess, TeamGroup, User)

AUDIT_KINDS = {"account-access", "content", "orca-link", "orca-access", "security"}


def now():
    return datetime.now(timezone.utc).isoformat()


def visible_project_ids(db, user):
    """None = everything visible (admin or no restrictions). Otherwise the set of allowed project ids."""
    restricted = {}
    for pa in db.scalars(select(ProjectAccess)):
        restricted.setdefault(pa.project_id, set()).add(pa.group_id)
    if not restricted or user.get("role") == "admin":
        return None
    me = db.scalar(select(User.id).where(User.username == user["username"]))
    mine = set(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == me)))
    allowed = {pid for pid, groups in restricted.items() if groups & mine}
    all_ids = set(db.scalars(select(Project.id)))
    return (all_ids - set(restricted)) | allowed


def can_see_project(db, user, project_id):
    ids = visible_project_ids(db, user)
    return ids is None or project_id in ids


def require_project(db, user, project_id):
    """404 for missing *and* hidden projects so restricted names do not leak."""
    if not db.get(Project, project_id) or not can_see_project(db, user, project_id):
        raise HTTPException(404, "Project not found")


class ChatUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank message")
        return value.strip()


class AccessInput(BaseModel):
    group_ids: list[int] = Field(default_factory=list, max_length=200)


def install_extra_routes(app, authenticated, admin):
    engine = app.state.engine

    def audit(db, actor, kind, summary):
        db.add(Event(kind=kind, state="ok", created=now(), summary=f"{actor}: {summary}"))

    # ---- attachments: uploader or admin may delete ---------------------------------
    @app.delete("/api/attachments/{file_id}")
    def delete_attachment(file_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            row = db.get(Attachment, file_id)
            if not row or not can_see_project(db, user, row.project_id):
                raise HTTPException(404, "File not found")
            owner = db.get(AttachmentOwner, file_id)
            if user["role"] != "admin" and (not owner or owner.uploaded_by != user["username"]):
                raise HTTPException(403, "Only the uploader or an administrator")
            key, name = row.key, row.name
            db.execute(delete(AttachmentOwner).where(AttachmentOwner.attachment_id == file_id))
            db.delete(row)
            audit(db, user["username"], "content", f"deleted attachment {name}")
            db.commit()
        app.state.storage.discard(key)  # best effort; the DB row is already gone
        return {"ok": True}

    # ---- chat: sender edits/deletes own message, admin may delete any -------------
    def own_message(db, message_id, user, allow_admin):
        m = db.get(ChatMessage, message_id)
        if not m:
            raise HTTPException(404, "Message not found")
        mine = m.sender_name == user["username"] and m.sender_id is not None
        if not mine and not (allow_admin and user["role"] == "admin"):
            raise HTTPException(403, "Only the sender")
        edit = db.get(ChatEdit, message_id)
        if edit and edit.deleted:
            raise HTTPException(409, "Message already deleted")
        return m, edit

    @app.patch("/api/chat/messages/{message_id}")
    def edit_message(message_id: int, data: ChatUpdate, user=Depends(authenticated)):
        with Session(engine) as db:
            m, edit = own_message(db, message_id, user, allow_admin=False)
            m.body = data.body
            if edit:
                edit.edited_at = now()
            else:
                db.add(ChatEdit(message_id=message_id, edited_at=now(), deleted=0))
            db.commit()
            return {"ok": True}

    @app.delete("/api/chat/messages/{message_id}")
    def delete_message(message_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            m, edit = own_message(db, message_id, user, allow_admin=True)
            m.body = ""
            if edit:
                edit.edited_at, edit.deleted = now(), 1
            else:
                db.add(ChatEdit(message_id=message_id, edited_at=now(), deleted=1))
            if m.sender_name != user["username"]:
                audit(db, user["username"], "content", f"deleted chat message {message_id} by {m.sender_name}")
            db.commit()
            return {"ok": True}

    # ---- project access by group (admin) ------------------------------------------
    @app.get("/api/admin/projects/{project_id}/access")
    def get_access(project_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            if not db.get(Project, project_id):
                raise HTTPException(404, "Project not found")
            return {"group_ids": sorted(db.scalars(select(ProjectAccess.group_id).where(ProjectAccess.project_id == project_id)))}

    @app.put("/api/admin/projects/{project_id}/access")
    def set_access(project_id: int, data: AccessInput, actor=Depends(admin)):
        with Session(engine) as db:
            p = db.get(Project, project_id)
            if not p:
                raise HTTPException(404, "Project not found")
            wanted = set(data.group_ids)
            if wanted and set(db.scalars(select(TeamGroup.id).where(TeamGroup.id.in_(wanted)))) != wanted:
                raise HTTPException(404, "Group not found")
            db.execute(delete(ProjectAccess).where(ProjectAccess.project_id == project_id))
            for gid in sorted(wanted):
                db.add(ProjectAccess(project_id=project_id, group_id=gid))
            audit(db, actor["username"], "account-access", f"project {p.name} access: {'all members' if not wanted else f'{len(wanted)} groups'}")
            db.commit()
            return {"ok": True, "restricted": bool(wanted)}

    # ---- activity log (admin) -----------------------------------------------------
    @app.get("/api/admin/audit")
    def audit_log(kind: str = Query("", max_length=30), q: str = Query("", max_length=80),
                  limit: int = Query(200, ge=1, le=500), actor=Depends(admin)):
        with Session(engine) as db:
            kinds = {kind} & AUDIT_KINDS if kind else AUDIT_KINDS
            query = select(Event).where(Event.kind.in_(kinds))
            if q:
                query = query.where(Event.summary.contains(q))
            rows = db.scalars(query.order_by(Event.id.desc()).limit(limit))
            return [{"id": e.id, "kind": e.kind, "state": e.state, "created": e.created, "summary": e.summary} for e in rows]


def forget_group_access(db, group_id):
    db.execute(delete(ProjectAccess).where(ProjectAccess.group_id == group_id))
