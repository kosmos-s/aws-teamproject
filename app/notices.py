"""Persistent dashboard inbox: no message bodies or private names in global notices."""

from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from .models import ChangeNotice, NoticeRead, Project, Note, Attachment, Task
from .extras import visible_project_ids
from .hardening import serialized, REACTION_LOCK


def notice_target(engine, path, data=None):
    bits = path.strip("/").split("/")
    if (
        not path.startswith("/api/")
        or "/chat/" in path
        or "/account/" in path
        or path.endswith("/orca")
        or path
        in {
            "/api/login",
            "/api/logout",
            "/api/activity",
            "/api/notices/read",
            "/api/admin/notices",
        }
    ):
        return None
    if len(bits) < 2:
        return None
    resource = bits[1]
    if resource in {"projects", "notes", "attachments", "tasks"}:
        pid = None
        if resource == "projects" and len(bits) > 2 and bits[2].isdigit():
            pid = int(bits[2])
            if len(bits) > 3 and bits[3] in {"notes", "attachments"}:
                resource = bits[3]
        elif (
            resource in {"notes", "attachments", "tasks"}
            and len(bits) > 2
            and bits[2].isdigit()
        ):
            with Session(engine) as db:
                row = db.get(
                    {"notes": Note, "attachments": Attachment, "tasks": Task}[resource],
                    int(bits[2]),
                )
                if row:
                    pid = row.project_id
        elif resource == "tasks" and data:
            pid = data.get("project_id")
        if pid is not None:
            return {
                "project_id": pid,
                "kind": resource,
                "title": {
                    "projects": "프로젝트",
                    "notes": "메모",
                    "attachments": "첨부파일",
                    "tasks": "할 일",
                }[resource]
                + " 변경",
                "admin_only": 0,
            }
        return None
    if (
        len(bits) > 4
        and bits[1:3] == ["admin", "projects"]
        and bits[3].isdigit()
        and bits[4] == "access"
    ):
        return {
            "project_id": int(bits[3]),
            "kind": "access",
            "title": "프로젝트 공개 범위 변경",
            "admin_only": 0,
        }
    if path.startswith("/api/admin/"):
        return {
            "project_id": None,
            "kind": "team",
            "title": "팀 운영 설정 변경",
            "admin_only": 1,
        }
    return None


def record_notice(engine, target, actor, method):
    with Session(engine) as db:
        target = dict(target)
        if target["project_id"] is not None:
            if not db.get(Project, target["project_id"]):
                return
            # /projects/:id/notes and attachments inherit the enclosing project.
        db.add(
            ChangeNotice(
                **target,
                actor=actor,
                body={
                    "POST": "추가 또는 실행",
                    "PUT": "설정 변경",
                    "PATCH": "수정",
                    "DELETE": "삭제",
                }.get(method, "변경"),
                created=datetime.now(timezone.utc).isoformat()
            )
        )
        db.commit()


class Announcement(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("title", "body")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("blank")
        return v.strip()


class ReadInput(BaseModel):
    last_id: int = Field(ge=0)


def install_routes(app, authenticated, admin):
    engine = app.state.engine

    def visible(db, user):
        q = select(ChangeNotice)
        if user["role"] != "admin":
            q = q.where(ChangeNotice.admin_only == 0)
        ids = visible_project_ids(db, user)
        # Deleted project notices are not turned into global notices.
        projects = (
            select(Project.id)
            if ids is None
            else select(Project.id).where(Project.id.in_(ids or {-1}))
        )
        return q.where(
            or_(
                ChangeNotice.project_id.is_(None), ChangeNotice.project_id.in_(projects)
            )
        )

    @app.get("/api/notices")
    def inbox(
        before: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=100),
        user=Depends(authenticated),
    ):
        with Session(engine) as db:
            q = visible(db, user)
            read = db.get(NoticeRead, user["id"])
            last = read.last_id if read else 0
            unread = (
                db.scalar(
                    select(func.count()).select_from(
                        q.where(ChangeNotice.id > last).subquery()
                    )
                )
                or 0
            )
            if before:
                q = q.where(ChangeNotice.id < before)
            rows = list(db.scalars(q.order_by(ChangeNotice.id.desc()).limit(limit + 1)))
            names = dict(
                db.execute(
                    select(Project.id, Project.name).where(
                        Project.id.in_(
                            {r.project_id for r in rows if r.project_id is not None}
                        )
                    )
                ).all()
            )
            items = [
                {
                    "id": r.id,
                    "project_id": r.project_id,
                    "kind": r.kind,
                    "title": r.title,
                    "body": r.body,
                    "project_name": names.get(r.project_id),
                    "actor": r.actor,
                    "created": r.created,
                    "unread": r.id > last,
                }
                for r in rows[:limit]
            ]
            return {
                "items": items,
                "unread": unread,
                "has_more": len(rows) > limit,
                "next_before": items[-1]["id"] if items else 0,
            }

    @app.post("/api/notices/read")
    @serialized(REACTION_LOCK)
    def mark(data: ReadInput, user=Depends(authenticated)):
        with Session(engine) as db:
            top = db.scalar(select(func.max(ChangeNotice.id))) or 0
            last = min(data.last_id, top)
            r = db.get(NoticeRead, user["id"])
            if not r:
                db.add(NoticeRead(user_id=user["id"], last_id=last))
            else:
                r.last_id = max(r.last_id, last)
            db.commit()
        return {"ok": True}

    @app.post("/api/admin/notices", status_code=201)
    def announce(data: Announcement, actor=Depends(admin)):
        with Session(engine) as db:
            r = ChangeNotice(
                project_id=None,
                kind="announcement",
                title=data.title,
                body=data.body,
                actor=actor["username"],
                admin_only=0,
                created=datetime.now(timezone.utc).isoformat(),
            )
            db.add(r)
            db.commit()
            identifier = r.id
        app.state.changes.publish("board")
        return {"id": identifier}
