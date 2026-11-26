"""Process one pending Orca link request (run by kosmos-orca-link.timer as root).

Fixed steps only, no shell, no user-controlled arguments beyond validated values:
  1. re-validate the GitHub URL and folder name
  2. clone as the `orca` user into /home/orca/projects/<folder> (or reuse a checkout of the same repo)
  3. `orca-ide repo add --path <dir> --json` as `orca`
  4. write the portal's orca_projects link and mark the request done/failed
"""
import os
import secrets
import stat

import subprocess
import sys
from datetime import datetime, timezone, timedelta
from functools import partial
from pathlib import Path

ROOT = Path("/opt/kosmos-portal")
sys.path.insert(0, str(ROOT))
PROJECTS = Path("/home/orca/projects")
FOLDER_SNAPSHOT_DIR = Path("/run/kosmos-orca-link")


def load_env():
    for line in Path("/etc/kosmos-portal.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def now():
    return datetime.now(timezone.utc).isoformat()


def as_orca(args, timeout):
    return run_as_orca("orca", Path("/home/orca"), args, timeout)


def run_as_orca(account, home, args, timeout, *, user_data=None):
    import pwd  # Linux only; imported here so the module loads in tests on any OS
    uid = pwd.getpwnam(account).pw_uid
    child_env={"PATH":"/usr/local/bin:/usr/bin:/bin","LANG":"C.UTF-8","HOME":str(home),
               "XDG_RUNTIME_DIR":f"/run/user/{uid}","DBUS_SESSION_BUS_ADDRESS":f"unix:path=/run/user/{uid}/bus",
               "GIT_TERMINAL_PROMPT":"0","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null"}
    if user_data is not None:
        child_env["ORCA_USER_DATA_PATH"] = str(user_data)
    clean=["/usr/bin/env","-i"]+[f"{key}={value}" for key,value in child_env.items()]
    if user_data is None:
        runner = ["/usr/sbin/runuser", "-u", account, "--"]
    else:
        runner = ["/usr/bin/systemd-run", "--wait", "--pipe", "--collect", "--quiet",
                  f"--uid={account}", f"--property=WorkingDirectory={home}",
                  f"--property=RuntimeMaxSec={timeout}s", "--property=NoNewPrivileges=yes",
                  "--property=ProtectHome=yes", "--property=ProtectProc=invisible",
                  "--property=SocketBindDeny=tcp:18000-18999", "--"]
    return subprocess.run(runner+clean+args,
                          env=child_env,capture_output=True,text=True,
                          timeout=timeout if user_data is None else timeout + 5)


def isolated_workspace(ports, project_id):
    import pwd
    from app.orca_project_runtime import project_account

    if project_id not in ports:
        raise RuntimeError("프로젝트 실행 환경이 등록되지 않았습니다")
    account, home = project_account(project_id)
    user = pwd.getpwnam(account)
    attrs = home.lstat()
    if (user.pw_uid == 0 or Path(user.pw_dir) != home or not stat.S_ISDIR(attrs.st_mode)
            or attrs.st_uid != user.pw_uid or stat.S_IMODE(attrs.st_mode) != 0o700):
        raise RuntimeError("프로젝트 실행 계정의 홈 설정이 올바르지 않습니다")
    projects = home / "projects"
    attrs = projects.lstat()
    if not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != user.pw_uid or attrs.st_mode & 0o022:
        raise RuntimeError("프로젝트 작업 디렉터리 설정이 올바르지 않습니다")
    child = partial(run_as_orca, account, home, user_data=home / ".config" / "orca")
    return child, projects, home / ".ssh" / "kosmos-deploy"


def origin_of(path, child=None):
    r = (as_orca if child is None else child)(["git", "-C", str(path), "remote", "get-url", "origin"], 20)
    return r.stdout.strip().removesuffix(".git").rstrip("/") if r.returncode == 0 else None


def short(text):
    return " ".join((text or "").split())[-300:]


def write_folder_snapshot(payload, directory=FOLDER_SNAPSHOT_DIR):
    """Publish through an open, trusted directory; readers only receive group read access."""
    import json
    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    tmp = None
    try:
        st = os.fstat(dir_fd)
        if (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) != (os.geteuid(), os.getegid(), 0o750):
            raise PermissionError("Folder snapshot directory must be owned by the worker and read-only to the portal")
        tmp_name = ".snapshot-" + secrets.token_hex(16)
        fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=dir_fd)
        tmp = tmp_name
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fchmod(stream.fileno(), 0o640)
        os.replace(tmp, "orca-folders.json", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        tmp = None
    finally:
        if tmp is not None:
            os.unlink(tmp, dir_fd=dir_fd)
        os.close(dir_fd)


def publish_folders(workspaces=None):
    """Publish the project list in the dedicated root-owned runtime directory."""
    from app.orca_admin import valid_folder
    items = {}
    for workspace in (PROJECTS,) if workspaces is None else workspaces:
        if not workspace.is_dir():
            continue
        for d in sorted(workspace.iterdir()):
            if d.is_dir() and not d.is_symlink() and valid_folder(d.name):
                items[d.name] = items.get(d.name, False) or (d / ".git").exists()
    folders = [{"name": name, "git": items[name]} for name in sorted(items)[:500]]
    write_folder_snapshot({"updated": now(), "folders": folders})


def require_legacy_request(db, req):
    from sqlalchemy import select
    from app.models import Project, ProjectRepository, OrcaLinkRequest
    identity=req.id
    db.rollback()  # Fresh snapshot before either checking or publishing a link.
    current=db.get(OrcaLinkRequest,identity)
    if not current or current.state not in {'pending','running'}:
        raise RuntimeError('Orca 연결 요청이 취소됐습니다')
    if not db.scalar(select(Project).where(Project.id==current.project_id).with_for_update()):
        raise RuntimeError('포털 프로젝트가 없습니다')
    if db.get(ProjectRepository,current.project_id):
        raise RuntimeError('프로젝트 저장소 설정이 변경됐습니다')
    return current


def process(db, req, *, workspace=None):
    from app.orca_admin import normalize_repo, valid_folder, NEW_FOLDER, EXISTING_FOLDER
    from app.models import OrcaProject, Project
    req = require_legacy_request(db,req)
    db.rollback()  # Do not keep the project lock during external commands.
    mode = "new" if req.repository_url == NEW_FOLDER else "existing" if req.repository_url == EXISTING_FOLDER else "github"
    url = normalize_repo(req.repository_url)[0] if mode == "github" else ""
    if not valid_folder(req.folder):
        raise RuntimeError("폴더 이름이 올바르지 않습니다")
    if not db.get(Project, req.project_id):
        raise RuntimeError("포털 프로젝트가 없습니다")
    child, projects = (as_orca, PROJECTS) if workspace is None else workspace(req.project_id)[:2]
    target = projects / req.folder
    if target.is_symlink() or target.resolve().parent != projects.resolve():
        raise RuntimeError("허용되지 않은 경로입니다")
    if mode == "new":
        if target.exists():
            raise RuntimeError("같은 이름의 폴더가 이미 있습니다. '서버 폴더 선택'을 쓰거나 다른 이름을 쓰세요")
        for args in (["mkdir", "--", str(target)], ["git", "init", "-q", "-b", "main", str(target)]):
            r = child(args, 30)
            if r.returncode != 0:
                raise RuntimeError("빈 프로젝트 생성 실패: " + short(r.stderr))
        step = "빈 프로젝트 생성(git init)"
    elif mode == "existing":
        if not target.is_dir() or target.is_symlink():
            raise RuntimeError("서버에 그 폴더가 없습니다")
        if not (target / ".git").exists():
            r = child(["git", "init", "-q", "-b", "main", str(target)], 30)
            if r.returncode != 0:
                raise RuntimeError("git 초기화 실패: " + short(r.stderr))
        step = "기존 서버 폴더 사용"
    elif target.exists():
        current_origin = origin_of(target) if workspace is None else origin_of(target, child)
        if current_origin != url:
            raise RuntimeError("같은 이름의 폴더가 다른 저장소로 이미 있습니다. 다른 폴더 이름을 쓰세요")
        step = "기존 체크아웃 사용"
    else:
        r = child(["git", "clone", "--", url, str(target)], 240)
        if r.returncode != 0:
            raise RuntimeError("clone 실패 (공개 저장소인지, 주소가 맞는지 확인): " + short(r.stderr))
        step = "clone 완료"
    r = child(["orca-ide", "repo", "add", "--path", str(target), "--json"], 90)
    if r.returncode != 0 and "already" not in (r.stdout + r.stderr).lower():
        raise RuntimeError("Orca 등록 실패: " + short(r.stderr or r.stdout))
    req = require_legacy_request(db,req)
    existing = db.get(OrcaProject, req.project_id)
    if existing:
        existing.label, existing.repository_url = req.folder, url
    else:
        db.add(OrcaProject(project_id=req.project_id, label=req.folder, repository_url=url))
    return f"{step} · Orca 등록 · 포털 연결 완료 ({target})"


def main_locked():
    load_env()
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import Base, OrcaLinkRequest, Event
    from app.orca_project_runtime import load_project_ports
    registry = os.getenv("ORCA_PROJECT_REGISTRY")
    workspace = None
    workspaces = None
    if registry is not None:
        ports = load_project_ports(registry)
        workspace = partial(isolated_workspace, ports)
        workspaces = []
        for project_id in ports:
            try:
                workspaces.append(workspace(project_id)[1])
            except (KeyError, OSError, RuntimeError):
                continue
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    Base.metadata.create_all(engine)
    from app.repository_worker import run_one
    if run_one(engine, as_orca, workspace=workspace):
        engine.dispose()
        return
    try:
        publish_folders(workspaces)
    except Exception:
        pass  # listing is a convenience; never block link processing
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
            req.detail = process(db, req, workspace=workspace)[:500]
            req.state = "done"
            try:
                publish_folders(workspaces)
            except Exception:
                pass
        except Exception as exc:  # report, never crash the timer
            db.rollback()
            req = db.get(OrcaLinkRequest, req.id)
            req.state, req.detail = "failed", (str(exc) or type(exc).__name__)[:500]
        req.finished = now()
        db.add(Event(kind="orca-link", state="ok" if req.state == "done" else "failed", created=now(),
                     summary=f"request {req.id} {req.repository_url} -> {req.folder}: {req.state}"))
        db.commit()


def main():
    import fcntl
    fd=os.open('/run/kosmos-orca-link-worker.lock',os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        main_locked()


if __name__ == "__main__":
    main()
