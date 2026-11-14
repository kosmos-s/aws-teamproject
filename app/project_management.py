"""Project ownership and fixed repository jobs. Filesystem work stays in the existing worker."""

import os
import hashlib
from datetime import datetime, timezone
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from .models import (
    Project,
    User,
    BlockedUser,
    ProjectOwner,
    ProjectRepository,
    ProjectDeployKey,
    ProjectJob,
    ProjectAccess,
    ProjectPolicy,
    ProjectArchive,
    Note,
    NoteEdit,
    Attachment,
    AttachmentOwner,
    Task,
    OrcaProject,
    OrcaLinkRequest,
    ChangeNotice,
    Event,
    TeamGroup,
    GroupMember,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def user_id(db, user):
    return user.get("id") or db.scalar(
        select(User.id).where(User.username == user["username"])
    )


def can_manage(db, user, pid):
    row = db.get(ProjectOwner, pid)
    return user["role"] == "admin" or bool(
        row and row.user_id == user_id(db, user) and user["role"] == "member"
    )


def require_manager(db, user, pid):
    project = db.scalar(select(Project).where(Project.id == pid).with_for_update())
    if not project:
        raise HTTPException(404, "Project not found")
    if not can_manage(db, user, pid):
        from .extras import require_project

        require_project(db, user, pid)
        raise HTTPException(403, "Project owner or administrator required")
    return project


def audit(db, user, summary):
    db.add(
        Event(
            kind="account-access",
            state="ok",
            created=now(),
            summary=f'{user["username"]}: {summary}',
        )
    )


def enqueue(db, user, repo, kind, generation=0):
    busy = db.scalar(
        select(ProjectJob.id).where(
            ProjectJob.project_id == repo.project_id,
            ProjectJob.state.in_(["pending", "running"]),
        )
    )
    if busy:
        raise HTTPException(409, "Project operation already pending")
    job = ProjectJob(
        project_id=repo.project_id,
        actor_id=user_id(db, user),
        revision=repo.revision,
        kind=kind,
        generation=generation,
        state="pending",
        detail="서버 고정 작업 대기",
        created=now(),
    )
    db.add(job)
    return job


def configure_repository(db, user, pid, url):
    from .orca_admin import normalize_repo

    try:
        url, slug = normalize_repo(url)
    except ValueError:
        raise HTTPException(422, "Invalid repository URL")
    existing = db.get(ProjectRepository, pid)
    if existing:
        if existing.repository_url != url:
            raise HTTPException(409, "Unlink repository before changing URL")
        return existing
    if db.scalar(
        select(OrcaLinkRequest.id)
        .where(
            OrcaLinkRequest.project_id == pid,
            OrcaLinkRequest.state.in_(["pending", "running"]),
        )
        .limit(1)
    ):
        raise HTTPException(409, "Legacy Orca connection already pending")
    if user["role"] != "admin":
        db.scalar(select(User).where(User.id == user_id(db, user)).with_for_update())
        count = (
            db.scalar(
                select(func.count(ProjectRepository.project_id))
                .join(
                    ProjectOwner,
                    ProjectOwner.project_id == ProjectRepository.project_id,
                )
                .where(ProjectOwner.user_id == user_id(db, user))
            )
            or 0
        )
        if count >= int(os.getenv("PROJECT_WORKSPACE_LIMIT", "5")):
            raise HTTPException(409, "Workspace limit reached")
    folder = (
        f"p{pid}-{slug[:65]}-{hashlib.sha256(url.lower().encode()).hexdigest()[:8]}"
    )
    from .orca_admin import valid_folder

    if not valid_folder(folder):
        raise HTTPException(422, "Invalid folder name")
    repo = ProjectRepository(
        project_id=pid, repository_url=url, folder=folder, revision=1, state="pending"
    )
    db.add(repo)
    db.flush()
    enqueue(db, user, repo, "link")
    return repo


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("blank")
        return v.strip()


class OwnerInput(BaseModel):
    user_id: int = Field(gt=0)


class RepositoryInput(BaseModel):
    repository_url: str = Field(min_length=1, max_length=255)


class DeleteInput(BaseModel):
    confirmation: str = Field(min_length=1, max_length=120)


def install_routes(app, authenticated, admin):
    engine = app.state.engine

    @app.get("/api/projects/{pid}/management-candidates")
    def candidates(pid: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            return [
                {"id": u.id, "username": u.username}
                for u in db.scalars(
                    select(User)
                    .where(
                        User.role.in_(["admin", "member"]),
                        User.id.not_in(select(BlockedUser.user_id)),
                    )
                    .order_by(User.username)
                )
            ]

    @app.get("/api/projects/{pid}/access/groups")
    def access_groups(pid: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            members = {}
            for row in db.scalars(select(GroupMember)):
                members.setdefault(row.group_id, []).append(row.user_id)
            return [
                {"id": g.id, "name": g.name, "user_ids": members.get(g.id, [])}
                for g in db.scalars(select(TeamGroup).order_by(TeamGroup.name))
            ]

    @app.patch("/api/projects/{pid}")
    def update(pid: int, data: ProjectUpdate, user=Depends(authenticated)):
        with Session(engine) as db:
            p = require_manager(db, user, pid)
            p.name, p.description = data.name, data.description.strip()
            audit(db, user, f"updated project {pid}")
            db.commit()
        return {"ok": True}

    @app.put("/api/projects/{pid}/owner")
    def transfer(pid: int, data: OwnerInput, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            target = db.get(User, data.user_id)
            if (
                not target
                or target.role not in {"member", "admin"}
                or db.get(BlockedUser, target.id)
            ):
                raise HTTPException(422, "Owner must be an active developer")
            owner = db.get(ProjectOwner, pid)
            if owner and owner.user_id == target.id:
                return {"ok": True}
            if owner:
                owner.user_id, owner.assigned_at = target.id, now()
            else:
                db.add(
                    ProjectOwner(project_id=pid, user_id=target.id, assigned_at=now())
                )
            repo = db.get(ProjectRepository, pid)
            if repo:
                repo.revision += 1
            for job in db.scalars(
                select(ProjectJob).where(
                    ProjectJob.project_id == pid,
                    ProjectJob.state.in_(["pending", "running"]),
                    ProjectJob.cleanup == 0,
                )
            ):
                job.state, job.finished = "cancelled", now()
            audit(db, user, f"project {pid} owner -> {target.username}")
            db.commit()
        return {"ok": True}

    @app.get("/api/projects/{pid}/repository")
    def repository(pid: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            repo = db.get(ProjectRepository, pid)
            key = db.get(ProjectDeployKey, pid)
            jobs = list(
                db.scalars(
                    select(ProjectJob)
                    .where(ProjectJob.project_id == pid)
                    .order_by(ProjectJob.id.desc())
                    .limit(10)
                )
            )
            return {
                "repository_url": repo.repository_url if repo else "",
                "folder": repo.folder if repo else "",
                "state": repo.state if repo else "none",
                "key": (
                    {
                        "public_key": key.public_key,
                        "fingerprint": key.fingerprint,
                        "state": key.state,
                        "verified_at": key.verified_at,
                        "write_verified": False,
                    }
                    if key
                    else None
                ),
                "shared_runtime": True,
                "jobs": [
                    {"id": j.id, "kind": j.kind, "state": j.state, "detail": j.detail}
                    for j in jobs
                ],
            }

    @app.put("/api/projects/{pid}/repository")
    def set_repository(pid: int, data: RepositoryInput, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            configure_repository(db, user, pid, data.repository_url)
            audit(db, user, f"configured repository for project {pid}")
            db.commit()
        return {"ok": True}

    @app.post("/api/projects/{pid}/repository/retry")
    def retry(pid: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            repo = db.get(ProjectRepository, pid)
            if not repo:
                raise HTTPException(409, "Configure repository first")
            enqueue(db, user, repo, "link")
            db.commit()
        return {"ok": True}

    @app.delete("/api/projects/{pid}/repository")
    def disconnect(pid: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_manager(db, user, pid)
            for job in db.scalars(
                select(ProjectJob).where(
                    ProjectJob.project_id == pid,
                    ProjectJob.state.in_(["pending", "running"]),
                    ProjectJob.cleanup == 0,
                )
            ):
                job.state, job.finished = "cancelled", now()
            key = db.get(ProjectDeployKey, pid)
            if key:
                db.add(
                    ProjectJob(
                        project_id=pid,
                        actor_id=user_id(db, user),
                        revision=0,
                        kind="key_remove",
                        generation=key.generation,
                        cleanup=1,
                        state="pending",
                        detail="서버 키 제거 대기",
                        created=now(),
                    )
                )
            for model in (ProjectDeployKey, ProjectRepository, OrcaProject):
                db.execute(delete(model).where(model.project_id == pid))
            audit(
                db,
                user,
                f"disconnected repository {pid}; workspace kept; remove GitHub deploy key separately",
            )
            db.commit()
        return {"ok": True, "workspace_preserved": True}

    @app.post("/api/projects/{pid}/deploy-key/{action}")
    def key_operation(pid: int, action: str, user=Depends(authenticated)):
        if action not in {"create", "verify", "remove"}:
            raise HTTPException(404, "Operation not found")
        with Session(engine) as db:
            require_manager(db, user, pid)
            repo = db.get(ProjectRepository, pid)
            if not repo:
                raise HTTPException(409, "Configure repository first")
            key = db.get(ProjectDeployKey, pid)
            if action == "create":
                if key and key.state not in {"removed", "failed", "needs_registration"}:
                    raise HTTPException(409, "Deploy key already exists")
                if not key:
                    key = ProjectDeployKey(
                        project_id=pid, generation=1, state="pending", created=now()
                    )
                    db.add(key)
                else:
                    key.generation += 1
                    key.state = "pending"
                    key.public_key = key.fingerprint = ""
                    key.verified_at = None
            elif not key:
                raise HTTPException(409, "Create deploy key first")
            if action == "verify" and (not key.public_key or key.state == "removed"):
                raise HTTPException(409, "Create deploy key first")
            enqueue(
                db,
                user,
                repo,
                {
                    "create": "key_create",
                    "verify": "key_verify",
                    "remove": "key_remove",
                }[action],
                key.generation,
            )
            audit(db, user, f"project {pid} deploy key {action} requested")
            db.commit()
        return {"ok": True}

    @app.delete("/api/projects/{pid}")
    def destroy(pid: int, data: DeleteInput, actor=Depends(admin)):
        from .hardening import queue_delete, drain_deletions

        with Session(engine) as db:
            project = require_manager(db, actor, pid)
            if data.confirmation != project.name:
                raise HTTPException(409, "Project confirmation mismatch")
            key = db.get(ProjectDeployKey, pid)
            if key:
                db.add(
                    ProjectJob(
                        project_id=pid,
                        actor_id=user_id(db, actor),
                        revision=0,
                        kind="key_remove",
                        generation=key.generation,
                        cleanup=1,
                        state="pending",
                        detail="프로젝트 삭제 후 서버 키 제거 대기",
                        created=now(),
                    )
                )
            for job in db.scalars(
                select(ProjectJob).where(
                    ProjectJob.project_id == pid,
                    ProjectJob.cleanup == 0,
                    ProjectJob.state.in_(["pending", "running"]),
                )
            ):
                job.state, job.finished = "cancelled", now()
            for f in db.scalars(select(Attachment).where(Attachment.project_id == pid)):
                queue_delete(db, f.key)
            db.execute(
                delete(AttachmentOwner).where(
                    AttachmentOwner.attachment_id.in_(
                        select(Attachment.id).where(Attachment.project_id == pid)
                    )
                )
            )
            db.execute(
                delete(NoteEdit).where(
                    NoteEdit.note_id.in_(select(Note.id).where(Note.project_id == pid))
                )
            )
            for model in (
                Task,
                Note,
                Attachment,
                ProjectAccess,
                ProjectPolicy,
                ProjectArchive,
                OrcaProject,
                OrcaLinkRequest,
                ProjectOwner,
                ProjectRepository,
                ProjectDeployKey,
                ChangeNotice,
            ):
                db.execute(delete(model).where(model.project_id == pid))
            db.execute(delete(Project).where(Project.id == pid))
            audit(
                db,
                actor,
                f"permanently deleted portal project {pid}; Orca folder retained; revoke GitHub deploy key separately",
            )
            db.commit()
        drain_deletions(engine, app.state.storage)
        return {
            "ok": True,
            "workspace_preserved": True,
            "github_key_revocation": "manual",
        }
