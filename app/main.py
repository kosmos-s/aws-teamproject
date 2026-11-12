import asyncio
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings
from .models import Base, User, LoginSession, Project, Note, Attachment, Event, OrcaProject, BlockedUser, ProjectArchive, NoteEdit
from .teamwork import activity, must_change as needs_password_change
from .models import AttachmentOwner, ProjectAccess, TeamGroup
from .extras import visible_project_ids, require_project, can_see_project
from .security import verify_password, token_hash, password_hash
from .storage import Storage


def now():
    return datetime.now(timezone.utc).isoformat()


class LoginInput(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=256)


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank name")
        return value.strip()


class NoteInput(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank note")
        return value.strip()


def create_app(settings=None):
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, pool_pre_ping=True,
                           connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    app = FastAPI(title="KOSMOS Operations", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.state.settings = settings
    app.state.storage = Storage(settings)
    failures = {}
    account_failures = {}  # per-username lockout, independent of client IP
    seen = {}  # user_id -> last time last_seen was written (throttle DB writes)
    replaced = {}  # token_hash -> time it was ended by a newer login of the same account
    FORCED_OK = {"/api/session", "/api/logout", "/api/account/password"}
    dummy_hash = password_hash("unmatched-dummy-password")

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Framework defaults echo invalid field values, including passwords.
        return JSONResponse({"detail": "Invalid input"}, status_code=422)

    @app.middleware("http")
    async def guards(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("origin") != settings.origin:
            return JSONResponse({"detail": "Origin rejected"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 2 * 1024 * 1024:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
            app.state.change_version += 1  # wakes every open /api/wait request
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, exc):
        return JSONResponse({"detail": "Database unavailable"}, status_code=503)

    def authenticated(request: Request):
        cookie = request.cookies.get("kosmos_session", "")
        with Session(engine) as db:
            hashed = token_hash(cookie)
            row = db.get(LoginSession, hashed)
            if not row or row.expires <= time.time():
                if hashed in replaced:
                    raise HTTPException(401, "Signed in elsewhere")
                raise HTTPException(401, "Login required")
            user = db.get(User, row.user_id)
            if not user or db.get(BlockedUser, user.id):
                raise HTTPException(401, "Login required")
            if user.role == "viewer" and request.method not in {"GET", "HEAD"} and request.url.path not in {"/api/logout", "/api/account/password"} and not request.url.path.startswith("/api/chat/"):
                raise HTTPException(403, "Read-only account")
            if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), row.csrf):
                raise HTTPException(403, "CSRF rejected")
            forced = needs_password_change(db, user.id)
            if forced and request.url.path not in FORCED_OK:
                raise HTTPException(403, "Password change required")
            if time.time() - seen.get(user.id, 0) > 60:
                seen[user.id] = time.time()
                activity(db, user.id).last_seen = now()
                db.commit()
            return {"username": user.username, "role": user.role, "csrf": row.csrf, "must_change": forced}

    @app.post("/api/login")
    def login(data: LoginInput, request: Request):
        key = request.client.host if request.client else "unknown"
        recent = [t for t in failures.get(key, []) if time.time() - t < 300]
        if len(recent) >= 5:
            raise HTTPException(429, "Try again in five minutes")
        account = data.username.strip().lower()[:80]
        account_recent = [t for t in account_failures.get(account, []) if time.time() - t < 900]
        if len(account_recent) >= 8:
            # Stops guessing one account from many IPs; checked before the password is tried.
            raise HTTPException(429, "Account temporarily locked")
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.username == data.username))
            valid = verify_password(data.password, user.password_hash if user else dummy_hash)
            if not user or not valid or db.get(BlockedUser, user.id):
                failures[key] = recent + [time.time()]
                account_failures[account] = account_recent + [time.time()]
                raise HTTPException(401, "Invalid credentials")
            failures.pop(key, None)
            account_failures.pop(account, None)
            db.execute(delete(LoginSession).where(LoginSession.expires <= time.time()))
            # One account = one active session: a new login ends every older session of the same account.
            ended = list(db.scalars(select(LoginSession.token_hash).where(LoginSession.user_id == user.id)))
            if ended:
                db.execute(delete(LoginSession).where(LoginSession.token_hash.in_(ended)))
            token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
            db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, csrf=csrf, expires=time.time() + 28800))
            act = activity(db, user.id)
            act.last_login = act.last_seen = now()
            db.commit()
        cutoff = time.time() - 30000
        for old in [k for k, t in replaced.items() if t < cutoff]:
            replaced.pop(old, None)
        for old in ended:
            replaced[old] = time.time()
            app.state.orca_revoke_hash(old)  # also close that browser's open Orca connection
        response = JSONResponse({"csrf": csrf, "ended_sessions": len(ended)})
        response.set_cookie("kosmos_session", token, max_age=28800, httponly=True, secure=settings.secure_cookies, samesite="lax")
        return response

    # Long-poll: the browser holds one request open; any successful write in this (single-worker)
    # process bumps the version and answers it at once, so chat appears without a 3 s polling delay.
    app.state.change_version = 0

    @app.get("/api/wait")
    async def wait_for_change(v: int = -1, user=Depends(authenticated)):
        deadline = time.monotonic() + 25
        while app.state.change_version == v and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        return {"v": app.state.change_version}

    @app.get("/api/session")
    def session(user=Depends(authenticated)):
        return user

    @app.post("/api/logout")
    def logout(request: Request, user=Depends(authenticated)):
        with Session(engine) as db:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(request.cookies.get("kosmos_session", ""))))
            db.commit()
        app.state.orca_revoke(request.cookies.get("kosmos_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("kosmos_session", secure=settings.secure_cookies, httponly=True, samesite="lax")
        return response

    @app.get("/api/projects")
    def projects(user=Depends(authenticated)):
        with Session(engine) as db:
            archived = {a.project_id: a for a in db.scalars(select(ProjectArchive))}
            visible = visible_project_ids(db, user)
            names = {g.id: g.name for g in db.scalars(select(TeamGroup))}
            access = {}
            for pa in db.scalars(select(ProjectAccess)):
                access.setdefault(pa.project_id, []).append(names.get(pa.group_id, "?"))
            return [{"id": p.id, "name": p.name, "description": p.description, "created": p.created,
                     "archived": p.id in archived, "access_groups": sorted(access.get(p.id, [])),
                     "orca_available": db.get(OrcaProject, p.id) is not None,
                     "repository_url": (db.get(OrcaProject, p.id).repository_url if db.get(OrcaProject, p.id) else None)}
                    for p in db.scalars(select(Project).order_by(Project.id)) if visible is None or p.id in visible]

    @app.post("/api/projects", status_code=201)
    def add_project(data: ProjectInput, user=Depends(authenticated)):
        with Session(engine) as db:
            p = Project(name=data.name, description=data.description, created=now())
            db.add(p)
            db.commit()
            return {"id": p.id, "name": p.name}

    @app.get("/api/notes")
    def notes(user=Depends(authenticated)):
        with Session(engine) as db:
            edits = {e.note_id: e for e in db.scalars(select(NoteEdit))}
            visible = visible_project_ids(db, user)
            query = select(Note)
            if visible is not None:
                query = query.where(Note.project_id.in_(visible or {-1}))
            return [{"id": n.id, "project_id": n.project_id, "body": n.body, "author": n.author, "created": n.created,
                     "edited": edits[n.id].edited_at if n.id in edits else None} for n in db.scalars(query.order_by(Note.id.desc()).limit(100))]

    @app.post("/api/projects/{project_id}/notes", status_code=201)
    def add_note(project_id: int, data: NoteInput, user=Depends(authenticated)):
        with Session(engine) as db:
            require_project(db, user, project_id)
            n = Note(project_id=project_id, body=data.body, author=user["username"], created=now())
            db.add(n)
            db.commit()
            return {"id": n.id}

    @app.post("/api/projects/{project_id}/attachments", status_code=201)
    def upload(project_id: int, file: UploadFile = File(...), user=Depends(authenticated)):
        allowed = {".txt": "text/plain", ".png": "image/png", ".jpg": "image/jpeg", ".pdf": "application/pdf"}
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        media = allowed.get(Path(name).suffix.lower())
        if not media or len(name) > 180 or any(ord(c) < 32 for c in name):
            raise HTTPException(415, "Allowed: txt, png, jpg, pdf")
        content = file.file.read(1024 * 1024 + 1)
        file.file.close()
        if len(content) > 1024 * 1024:
            raise HTTPException(413, "Maximum 1 MiB")
        with Session(engine) as db:
            require_project(db, user, project_id)
            key = "attachments/" + secrets.token_hex(16)
            try:
                app.state.storage.put(key, content, media)
            except Exception:
                raise HTTPException(503, "Storage unavailable")
            row = Attachment(project_id=project_id, name=name, key=key, media_type=media, size=len(content))
            db.add(row)
            db.flush()
            db.add(AttachmentOwner(attachment_id=row.id, uploaded_by=user["username"], uploaded_at=now()))
            db.commit()
            return {"id": row.id, "name": row.name}

    @app.get("/api/projects/{project_id}/attachments")
    def attachments(project_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            require_project(db, user, project_id)
            owners = {o.attachment_id: o.uploaded_by for o in db.scalars(select(AttachmentOwner))}
            return [{"id": a.id, "name": a.name, "size": a.size, "uploaded_by": owners.get(a.id)}
                    for a in db.scalars(select(Attachment).where(Attachment.project_id == project_id))]

    @app.get("/api/attachments/{file_id}")
    def download(file_id: int, user=Depends(authenticated)):
        with Session(engine) as db:
            row = db.get(Attachment, file_id)
            if not row or not can_see_project(db, user, row.project_id):
                raise HTTPException(404, "File not found")
            try:
                content = app.state.storage.get(row.key)
            except Exception:
                raise HTTPException(503, "Storage unavailable")
            return Response(content, media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.name, safe="")})

    @app.get("/api/events")
    def events(user=Depends(authenticated)):
        with Session(engine) as db:
            query = select(Event)
            if user["role"] != "admin":
                # Account/content audit entries are for administrators (see /api/admin/audit).
                query = query.where(Event.kind.in_(["monitor", "backup", "restore", "code-backup", "external-monitor"]))
            return [{"id": e.id, "kind": e.kind, "state": e.state, "created": e.created, "summary": e.summary} for e in db.scalars(query.order_by(Event.id.desc()).limit(100))]

    @app.get("/api/status")
    def status(user=Depends(authenticated)):
        with Session(engine) as db:
            event = db.scalar(select(Event).where(Event.kind == "monitor").order_by(Event.id.desc()))
            if not event:
                return {"state": "unknown", "summary": "No check recorded"}
            stale = (datetime.now(timezone.utc) - datetime.fromisoformat(event.created)).total_seconds() > 180
            return {"state": "stale" if stale else event.state, "summary": event.summary, "created": event.created}

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return {"state": "ok"}

    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")

    from .orca_gateway import install_orca_routes
    install_orca_routes(app, settings, authenticated)
    from .collab import install_collab_routes
    install_collab_routes(app, authenticated)
    from .team_controls import install_team_routes
    install_team_routes(app, settings, authenticated)
    return app
