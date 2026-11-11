import json
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .models import User, BlockedUser, LoginSession, Event, UserActivity
from .collab import forget_user_chat
from .teamwork import install_teamwork_routes, set_must_change, forget_user_teamwork, user_groups
from .security import create_user, password_hash, verify_password, token_hash


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(min_length=8, max_length=256)


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: Literal["admin", "member", "viewer"] = "member"


class AccessChange(BaseModel):
    active: bool
    role: Literal["admin", "member", "viewer"]


class ResourceState(BaseModel):
    kind: str = Field(max_length=40)
    label: str = Field(max_length=120)
    state: str = Field(max_length=40)
    cleanup: Literal["unknown", "pending", "retained", "deleted"] = "unknown"


class OperationsSnapshot(BaseModel):
    captured_at: datetime
    stop_at: datetime | None = None
    resources: list[ResourceState] = Field(max_length=30)
    monthly_estimate_usd: float = Field(ge=0, le=10000)
    estimate_date: str = Field(max_length=30)
    backup_retention_days: int = Field(ge=1, le=365)


def read_operations(path):
    if not path.exists():
        return {"state": "unknown", "detail": "No operator snapshot; no live AWS check performed"}
    try:
        if path.stat().st_size > 32768:
            raise ValueError("snapshot too large")
        data = OperationsSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        if data.captured_at.tzinfo is None or (data.stop_at and data.stop_at.tzinfo is None):
            raise ValueError("UTC offset required")
        age = (datetime.now(timezone.utc) - data.captured_at).total_seconds()
        if age < -60:
            raise ValueError("future snapshot")
        return {"state": "stale" if age > 3600 else "current", "source": "operator snapshot", "billing": "estimate, not actual charges", **data.model_dump(mode="json")}
    except (ValueError, OSError, ValidationError):
        return {"state": "unknown", "detail": "Invalid operator snapshot; no live AWS check performed"}


def install_team_routes(app, settings, authenticated):
    engine = app.state.engine

    def admin(user=Depends(authenticated)):
        if user["role"] != "admin":
            raise HTTPException(403, "Administrator required")
        return user

    from .orca_admin import install_orca_admin_routes
    install_orca_admin_routes(app, admin)
    install_teamwork_routes(app, authenticated, admin)

    def audit(db, actor, summary):
        db.add(Event(kind="account-access", state="ok", created=datetime.now(timezone.utc).isoformat(), summary=f"{actor}: {summary}"))

    @app.get("/api/admin/users")
    def users(actor=Depends(admin)):
        with Session(engine) as db:
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            live = {}
            for uid in db.scalars(select(LoginSession.user_id).where(LoginSession.expires > time.time())):
                live[uid] = live.get(uid, 0) + 1
            acts = {a.user_id: a for a in db.scalars(select(UserActivity))}
            return [{"id": u.id, "username": u.username, "role": u.role, "active": u.id not in blocked,
                     "sessions": live.get(u.id, 0), "last_login": acts[u.id].last_login if u.id in acts else None,
                     "must_change": bool(acts[u.id].must_change) if u.id in acts else False,
                     "groups": [g.name for g in user_groups(db, u.id)]} for u in db.scalars(select(User).order_by(User.id))]

    @app.post("/api/admin/users", status_code=201)
    def add_user(data: NewUser, actor=Depends(admin)):
        try:
            create_user(engine, data.username, data.password, data.role)
        except IntegrityError:
            raise HTTPException(409, "Username already exists")
        with Session(engine) as db:
            uid = db.scalar(select(User.id).where(User.username == data.username))
            set_must_change(db, uid, True)  # admin-chosen initial password must be replaced at first login
            audit(db, actor["username"], f"created {data.username} role={data.role}")
            db.commit()
        return {"username": data.username, "role": data.role, "active": True}

    @app.patch("/api/admin/users/{user_id}")
    def update_access(user_id: int, data: AccessChange, actor=Depends(admin)):
        with Session(engine) as db:
            # Serialize administrator changes to prevent simultaneous last-admin removal.
            all_users = list(db.scalars(select(User).order_by(User.id).with_for_update()))
            target = next((u for u in all_users if u.id == user_id), None)
            if not target:
                raise HTTPException(404, "User not found")
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            removing_admin = target.role == "admin" and (not data.active or data.role != "admin")
            if (target.username == actor["username"] and (not data.active or data.role != "admin")) or (removing_admin and sum(u.role == "admin" and u.id not in blocked for u in all_users) <= 1):
                raise HTTPException(409, "Cannot lock current or last administrator")
            target.role = data.role
            if data.active:
                db.execute(delete(BlockedUser).where(BlockedUser.user_id == user_id))
            elif user_id not in blocked:
                db.add(BlockedUser(user_id=user_id))
            tokens = list(db.scalars(select(LoginSession.token_hash).where(LoginSession.user_id == user_id)))
            db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
            audit(db, actor["username"], f"access {target.username} active={data.active} role={data.role}; sessions revoked")
            db.commit()
        for token in tokens:
            app.state.orca_revoke_hash(token)
        return {"ok": True, "sessions_revoked": len(tokens)}

    def revoke_sessions(db, user_id, keep=None):
        query = select(LoginSession.token_hash).where(LoginSession.user_id == user_id)
        tokens = [t for t in db.scalars(query) if t != keep]
        if tokens:
            db.execute(delete(LoginSession).where(LoginSession.token_hash.in_(tokens)))
        return tokens

    @app.put("/api/admin/users/{user_id}/password")
    def reset_password(user_id: int, data: PasswordReset, actor=Depends(admin)):
        with Session(engine) as db:
            target = db.get(User, user_id)
            if not target:
                raise HTTPException(404, "User not found")
            if target.username == actor["username"]:
                raise HTTPException(409, "Use your own password change")
            target.password_hash = password_hash(data.password)
            set_must_change(db, user_id, True)
            tokens = revoke_sessions(db, user_id)
            audit(db, actor["username"], f"password reset {target.username}; sessions revoked")
            db.commit()
        for token in tokens:
            app.state.orca_revoke_hash(token)
        return {"ok": True, "sessions_revoked": len(tokens)}

    @app.delete("/api/admin/users/{user_id}")
    def delete_user(user_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            # Same lock as update_access so two admins cannot remove the last admin together.
            all_users = list(db.scalars(select(User).order_by(User.id).with_for_update()))
            target = next((u for u in all_users if u.id == user_id), None)
            if not target:
                raise HTTPException(404, "User not found")
            if target.username == actor["username"]:
                raise HTTPException(409, "Cannot delete current account")
            blocked = set(db.scalars(select(BlockedUser.user_id)))
            if target.role == "admin" and target.id not in blocked and sum(u.role == "admin" and u.id not in blocked for u in all_users) <= 1:
                raise HTTPException(409, "Cannot delete last administrator")
            tokens = revoke_sessions(db, user_id)
            db.execute(delete(BlockedUser).where(BlockedUser.user_id == user_id))
            forget_user_chat(db, user_id)
            forget_user_teamwork(db, user_id)
            name = target.username
            db.delete(target)
            audit(db, actor["username"], f"deleted {name}; sessions revoked")
            db.commit()
        for token in tokens:
            app.state.orca_revoke_hash(token)
        return {"ok": True, "deleted": name}

    @app.post("/api/account/password")
    def change_own_password(data: PasswordChange, request: Request, user=Depends(authenticated)):
        current_token = token_hash(request.cookies.get("kosmos_session", ""))
        with Session(engine) as db:
            me = db.scalar(select(User).where(User.username == user["username"]))
            if not me:
                raise HTTPException(404, "User not found")
            if not verify_password(data.current, me.password_hash):
                # 403, not 401: a wrong current password must not log the user out.
                raise HTTPException(403, "Current password incorrect")
            if verify_password(data.new, me.password_hash):
                raise HTTPException(409, "New password must differ")
            me.password_hash = password_hash(data.new)
            set_must_change(db, me.id, False)
            tokens = revoke_sessions(db, me.id, keep=current_token)
            audit(db, me.username, "changed own password; other sessions revoked")
            db.commit()
        for token in tokens:
            app.state.orca_revoke_hash(token)
        return {"ok": True, "other_sessions_revoked": len(tokens)}

    @app.get("/api/admin/operations")
    def operations(actor=Depends(admin)):
        return read_operations(settings.data_dir / "operations.json")
