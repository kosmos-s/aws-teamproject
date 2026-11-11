"""Process one pending Orca link request (run by kosmos-orca-link.timer as root).

Fixed steps only, no shell, no user-controlled arguments beyond validated values:
  1. re-validate the GitHub URL and folder name
  2. clone as the `orca` user into /home/orca/projects/<folder> (or reuse a checkout of the same repo)
  3. `orca-ide repo add --path <dir> --json` as `orca`
  4. write the portal's orca_projects link and mark the request done/failed
"""
import os

import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/opt/kosmos-portal")
sys.path.insert(0, str(ROOT))
PROJECTS = Path("/home/orca/projects")


def load_env():
    for line in Path("/etc/kosmos-portal.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def now():
    return datetime.now(timezone.utc).isoformat()


def as_orca(args, timeout):
    import pwd  # Linux only; imported here so the module loads in tests on any OS
    uid = pwd.getpwnam("orca").pw_uid
    env = ["env", f"XDG_RUNTIME_DIR=/run/user/{uid}", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
           "GIT_TERMINAL_PROMPT=0", "HOME=/home/orca"]
    return subprocess.run(["runuser", "-u", "orca", "--"] + env + args, capture_output=True, text=True, timeout=timeout)


def origin_of(path):
    r = as_orca(["git", "-C", str(path), "remote", "get-url", "origin"], 20)
    return r.stdout.strip().removesuffix(".git").rstrip("/") if r.returncode == 0 else None


def short(text):
    return " ".join((text or "").split())[-300:]


def process(db, req):
    from app.orca_admin import normalize_repo, valid_folder
    from app.models import OrcaProject, Project
    url, _ = normalize_repo(req.repository_url)
    if not valid_folder(req.folder):
        raise RuntimeError("폴더 이름이 올바르지 않습니다")
    if not db.get(Project, req.project_id):
        raise RuntimeError("포털 프로젝트가 없습니다")
    target = PROJECTS / req.folder
    if target.resolve().parent != PROJECTS.resolve():
        raise RuntimeError("허용되지 않은 경로입니다")
    if target.exists():
        if origin_of(target) != url:
            raise RuntimeError("같은 이름의 폴더가 다른 저장소로 이미 있습니다. 다른 폴더 이름을 쓰세요")
        step = "기존 체크아웃 사용"
    else:
        r = as_orca(["git", "clone", "--", url, str(target)], 240)
        if r.returncode != 0:
            raise RuntimeError("clone 실패 (공개 저장소인지, 주소가 맞는지 확인): " + short(r.stderr))
        step = "clone 완료"
    r = as_orca(["orca-ide", "repo", "add", "--path", str(target), "--json"], 90)
    if r.returncode != 0 and "already" not in (r.stdout + r.stderr).lower():
        raise RuntimeError("Orca 등록 실패: " + short(r.stderr or r.stdout))
    existing = db.get(OrcaProject, req.project_id)
    if existing:
        existing.label, existing.repository_url = req.folder, url
    else:
        db.add(OrcaProject(project_id=req.project_id, label=req.folder, repository_url=url))
    return f"{step} · Orca 등록 · 포털 연결 완료 ({target})"


def main():
    load_env()
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import Base, OrcaLinkRequest, Event
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        # A request stuck in "running" for 10 minutes means a previous run died; fail it visibly.
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        for stale in db.scalars(select(OrcaLinkRequest).where(OrcaLinkRequest.state == "running", OrcaLinkRequest.created < cutoff)):
            stale.state, stale.detail, stale.finished = "failed", "작업이 중간에 멈췄습니다. 다시 요청하세요", now()
        db.commit()
        req = db.scalar(select(OrcaLinkRequest).where(OrcaLinkRequest.state == "pending").order_by(OrcaLinkRequest.id).with_for_update())
        if not req:
            return
        req.state, req.detail = "running", "서버에서 처리 중"
        db.commit()
        try:
            req.detail = process(db, req)[:500]
            req.state = "done"
        except Exception as exc:  # report, never crash the timer
            db.rollback()
            req = db.get(OrcaLinkRequest, req.id)
            req.state, req.detail = "failed", (str(exc) or type(exc).__name__)[:500]
        req.finished = now()
        db.add(Event(kind="orca-link", state="ok" if req.state == "done" else "failed", created=now(),
                     summary=f"request {req.id} {req.repository_url} -> {req.folder}: {req.state}"))
        db.commit()


if __name__ == "__main__":
    main()
