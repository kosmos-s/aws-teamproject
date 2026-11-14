"""Admin: connect a GitHub repository to Orca and link it to a portal project.

The web never runs commands. It validates and records a request; the fixed worker
(deploy/orca-link-worker.py, root systemd timer) clones as the `orca` user and registers it.
"""
import json
import re
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .models import Project, OrcaProject, OrcaLinkRequest, Event

GITHUB_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,100})/([A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?$")
FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
# Non-GitHub modes are stored as these markers in repository_url (no schema change needed).
NEW_FOLDER, EXISTING_FOLDER = "(new)", "(existing)"


def normalize_repo(url):
    """Return (canonical https URL without .git, default folder) or raise ValueError."""
    m = GITHUB_URL.fullmatch((url or "").strip())
    if not m or m.group(2) in {".", ".."}:
        raise ValueError("Only public https://github.com/<owner>/<repo> URLs are allowed")
    owner, repo = m.group(1), m.group(2)
    return f"https://github.com/{owner}/{repo}", repo


def valid_folder(name):
    return bool(FOLDER.fullmatch(name or "")) and name not in {".", ".."} and ".." not in name


class LinkInput(BaseModel):
    project_id: int
    mode: str = Field(default="github", pattern=r"^(github|new|existing)$")
    repository_url: str = Field(default="", max_length=255)
    folder: str = Field(default="", max_length=100)


def read_folders(data_dir):
    """Folder list published by the root worker; the portal user cannot read /home/orca itself."""
    try:
        data = json.loads((data_dir / "orca-folders.json").read_text(encoding="utf-8"))
        return {"folders": [f for f in data.get("folders", []) if valid_folder(f.get("name", ""))][:500],
                "updated": data.get("updated")}
    except (OSError, ValueError, AttributeError):
        return {"folders": [], "updated": None}


def install_orca_admin_routes(app, admin):
    engine = app.state.engine
    data_dir = app.state.settings.data_dir

    def audit(db, actor, summary):
        db.add(Event(kind="orca-link", state="ok", created=datetime.now(timezone.utc).isoformat(), summary=f"{actor}: {summary}"))

    @app.get("/api/admin/orca")
    def orca_overview(actor=Depends(admin)):
        with Session(engine) as db:
            projects = {p.id: p.name for p in db.scalars(select(Project).order_by(Project.id))}
            maps = list(db.scalars(select(OrcaProject)))
            reqs = list(db.scalars(select(OrcaLinkRequest).order_by(OrcaLinkRequest.id.desc()).limit(20)))
            linked = {m.project_id for m in maps}
            return {
                "projects": [{"id": i, "name": n, "linked": i in linked} for i, n in projects.items()],
                "mappings": [{"project_id": m.project_id, "project": projects.get(m.project_id, "?"), "label": m.label,
                              "repository_url": m.repository_url} for m in maps],
                "server_folders": read_folders(data_dir),
                "requests": [{"id": r.id, "project": projects.get(r.project_id, "?"), "repository_url": r.repository_url,
                              "folder": r.folder, "state": r.state, "detail": r.detail, "requested_by": r.requested_by,
                              "created": r.created, "finished": r.finished} for r in reqs],
            }

    @app.post("/api/admin/orca-links", status_code=201)
    def request_link(data: LinkInput, actor=Depends(admin)):
        if data.mode == "github":
            try:
                url, default_folder = normalize_repo(data.repository_url)
            except ValueError:
                raise HTTPException(422, "Invalid repository URL")
        else:
            url, default_folder = (NEW_FOLDER if data.mode == "new" else EXISTING_FOLDER), ""
        folder = (data.folder or default_folder).strip()
        if not valid_folder(folder):
            raise HTTPException(422, "Invalid folder name")
        with Session(engine) as db:
            if not db.scalar(select(Project).where(Project.id==data.project_id).with_for_update()):
                raise HTTPException(404, "Project not found")
            from .models import ProjectRepository
            if db.get(ProjectRepository,data.project_id):raise HTTPException(409,'Use project repository settings')
            if db.get(OrcaProject, data.project_id):
                raise HTTPException(409, "Project already linked to Orca")
            busy = db.scalar(select(OrcaLinkRequest).where(OrcaLinkRequest.state.in_(["pending", "running"]),
                                                           (OrcaLinkRequest.project_id == data.project_id) | (OrcaLinkRequest.folder == folder)))
            if busy:
                raise HTTPException(409, "Link request already in progress")
            r = OrcaLinkRequest(project_id=data.project_id, repository_url=url, folder=folder, state="pending",
                                detail="대기 중 (서버 작업이 20초 안에 처리합니다)", requested_by=actor["username"],
                                created=datetime.now(timezone.utc).isoformat())
            db.add(r)
            audit(db, actor["username"], f"requested Orca link project={data.project_id} {url} -> {folder}")
            db.commit()
            return {"id": r.id, "state": r.state, "repository_url": url, "folder": folder}

    @app.delete("/api/admin/orca-projects/{project_id}")
    def unlink(project_id: int, actor=Depends(admin)):
        with Session(engine) as db:
            from .models import ProjectRepository
            if db.get(ProjectRepository,project_id):raise HTTPException(409,'Use project repository settings')
            row = db.get(OrcaProject, project_id)
            if not row:
                raise HTTPException(404, "Orca link not found")
            db.execute(delete(OrcaProject).where(OrcaProject.project_id == project_id))
            audit(db, actor["username"], f"removed Orca link project={project_id} (server folder kept)")
            db.commit()
        return {"ok": True}
