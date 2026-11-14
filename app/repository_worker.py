"""Fixed repository/key steps, called only by the existing root timer, as the shared orca user."""

import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import shutil
from sqlalchemy import select
from .models import (
    Project,
    User,
    BlockedUser,
    ProjectOwner,
    ProjectRepository,
    ProjectDeployKey,
    ProjectJob,
    OrcaProject,
)
from .orca_admin import normalize_repo, valid_folder

PROJECTS = Path("/home/orca/projects")
KEYS = Path("/home/orca/.ssh/kosmos-deploy")
# Public GitHub Ed25519 host key from GitHub's official SSH fingerprints documentation.
GITHUB_HOST_KEY = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
WRITE_FILE = """from pathlib import Path
import base64,sys
p=Path(sys.argv[1])
if p.is_symlink():raise ValueError('Symlink refused')
p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
p.parent.chmod(0o700)
p.write_bytes(base64.b64decode(sys.argv[2]));p.chmod(int(sys.argv[3],8))
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def available_disk():
    return shutil.disk_usage(PROJECTS).free >= 2 * 1024**3


def checked(child, args, timeout=30):
    result = child(args, timeout)
    if result.returncode:
        raise ValueError(
            "고정 서버 작업이 실패했습니다. 주소·키 등록·네트워크를 확인하세요."
        )
    return result.stdout


def write_public(child, path, text, mode="600"):
    checked(
        child,
        [
            "python3",
            "-c",
            WRITE_FILE,
            str(path),
            base64.b64encode(text.encode()).decode(),
            mode,
        ],
    )


def key_paths(pid, generation):
    if (
        not isinstance(pid, int)
        or pid <= 0
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise ValueError("Invalid key identity")
    return KEYS / f"p{pid}-g{generation}.key", KEYS / f"p{pid}.conf"


def ssh_configuration(pid, generation):
    key, config = key_paths(pid, generation)
    return (
        "Host github.com\n  HostName ssh.github.com\n  Port 443\n  User git\n"
        f"  IdentityFile {key}\n  IdentitiesOnly yes\n  BatchMode yes\n"
        f"  StrictHostKeyChecking yes\n  HostKeyAlias github.com\n  UserKnownHostsFile {KEYS}/github_known_hosts\n  GlobalKnownHostsFile /dev/null\n"
    )


def git_args(pid, generation, *args):
    _, config = key_paths(pid, generation)
    # Git invokes this fixed command internally. It contains only a generated integer path, never web text.
    return [
        "git",
        "-c",
        f"core.sshCommand=ssh -F {config}",
        "-c",
        "credential.helper=",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        *args,
    ]


def authorize(db, job):
    identity = job.id
    # Expiring ORM objects alone retains MySQL's repeatable-read snapshot.
    # No pending metadata writes are permitted before these phase boundaries.
    db.rollback()
    current = db.get(ProjectJob, identity)
    if not current or current.state not in {"pending", "running"}:
        raise ValueError("작업이 취소됐습니다")
    if job.cleanup and job.kind == "key_remove":
        return None, None
    repo = db.get(ProjectRepository, job.project_id)
    owner = db.get(ProjectOwner, job.project_id)
    actor = db.get(User, job.actor_id)
    if (
        not db.get(Project, job.project_id)
        or not repo
        or repo.revision != job.revision
        or not actor
        or db.get(BlockedUser, actor.id)
    ):
        raise ValueError("프로젝트 또는 요청 권한이 변경됐습니다")
    if actor.role != "admin" and not (
        actor.role == "member" and owner and owner.user_id == actor.id
    ):
        raise ValueError("소유자 권한이 변경됐습니다")
    return repo, db.get(ProjectDeployKey, job.project_id)


def remove_keys(child, pid):
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError("Invalid project identity")
    cleanup = """from pathlib import Path
import re,sys
root=Path(sys.argv[1]);pid=int(sys.argv[2])
if root.is_symlink():raise ValueError('Symlink refused')
if root.exists():
 for p in root.iterdir():
  if re.fullmatch(r'p'+str(pid)+r'(?:-g[0-9]+\\.key(?:\\.pub)?|\\.conf)',p.name):p.unlink(missing_ok=True)
"""
    checked(child, ["python3", "-c", cleanup, str(KEYS), str(pid)])


def process(db, job, child):
    if job.kind not in {"link", "key_create", "key_verify", "key_remove"}:
        raise ValueError("지원하지 않는 고정 작업")
    repo, key = authorize(db, job)
    if job.kind == "key_remove":
        remove_keys(child, job.project_id)
        _, key = authorize(db, job)
        if key:
            key.state = "removed"
            key.public_key = key.fingerprint = ""
            key.verified_at = None
        return "done"
    url, unused = normalize_repo(repo.repository_url)
    if not valid_folder(repo.folder):
        raise ValueError("Invalid folder")
    target = PROJECTS / repo.folder
    if target.is_symlink() or target.resolve().parent != PROJECTS.resolve():
        raise ValueError("Invalid workspace path")
    if job.kind == "key_create":
        if not key or key.generation != job.generation:
            raise ValueError("키 요청이 변경됐습니다")
        private, config = key_paths(job.project_id, key.generation)
        checked(child, ["mkdir", "-p", "-m", "700", "--", str(KEYS)])
        remove_keys(child, job.project_id)
        checked(
            child,
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                f"kosmos-p{job.project_id}",
                "-f",
                str(private),
            ],
        )
        public = checked(child, ["cat", "--", str(private) + ".pub"]).strip()
        if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9_-]+)?", public):
            raise ValueError("Invalid public key")
        fingerprint = checked(
            child, ["ssh-keygen", "-l", "-E", "sha256", "-f", str(private) + ".pub"]
        )
        found = re.search(r"SHA256:[A-Za-z0-9+/]+", fingerprint)
        if not found:
            raise ValueError("Invalid public fingerprint")
        write_public(child, KEYS / "github_known_hosts", GITHUB_HOST_KEY)
        write_public(child, config, ssh_configuration(job.project_id, key.generation))
        authorize(db, job)
        key = db.get(ProjectDeployKey, job.project_id)
        key.public_key = public
        key.fingerprint = found.group()
        key.state = "awaiting_registration"
        key.created = now()
        return "done"
    if not available_disk():
        raise ValueError("서버 여유 공간이 2GiB 미만입니다")
    use_key = bool(
        key and key.public_key and key.state not in {"removed", "needs_registration"}
    )
    ssh_url = "git@github.com:" + url.removeprefix("https://github.com/") + ".git"
    verified = False
    if job.kind == "key_verify":
        if not use_key:
            raise ValueError("먼저 키를 준비하고 GitHub에 등록하세요")
        checked(
            child,
            git_args(job.project_id, key.generation, "ls-remote", "--", ssh_url),
            60,
        )
        authorize(db, job)
        verified = True
    if target.exists():
        if (target / ".git").is_symlink() or (target / ".git").is_file():
            raise ValueError("공유 Git worktree 대신 전용 체크아웃을 사용하세요")
        origin = (
            checked(child, ["git", "-C", str(target), "remote", "get-url", "origin"])
            .strip()
            .removesuffix(".git")
            .rstrip("/")
        )
        if origin not in {url, ssh_url.removesuffix(".git")}:
            raise ValueError("폴더가 다른 저장소에 연결돼 있습니다")
    else:
        args = (
            git_args(
                job.project_id,
                key.generation,
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--",
                ssh_url,
                str(target),
            )
            if use_key
            else [
                "git",
                "-c",
                "credential.helper=",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--",
                url,
                str(target),
            ]
        )
        result = child(args, 240)
        if result.returncode:
            repo, _ = authorize(db, job)
            repo.state = "waiting_key" if not use_key else "failed"
            return "waiting_key" if not use_key else "failed"
    if use_key:
        authorize(db, job)
        checked(
            child,
            [
                "git",
                "-C",
                str(target),
                "config",
                "--local",
                "core.sshCommand",
                f"ssh -F {key_paths(job.project_id,key.generation)[1]}",
            ],
        )
        checked(
            child, ["git", "-C", str(target), "remote", "set-url", "origin", ssh_url]
        )
        result = child(
            [
                "git",
                "-C",
                str(target),
                "config",
                "--local",
                "--unset-all",
                "remote.origin.pushurl",
            ],
            30,
        )
        if result.returncode not in {0, 5}:
            raise ValueError("기존 push 주소 설정을 정리하지 못했습니다")
    authorize(db, job)
    result = child(["orca-ide", "repo", "add", "--path", str(target), "--json"], 90)
    if result.returncode and "already" not in (result.stdout + result.stderr).lower():
        raise ValueError("Orca 폴더 등록 실패")
    repo, _ = authorize(db, job)
    mapping = db.get(OrcaProject, job.project_id)
    if mapping:
        mapping.label, mapping.repository_url = repo.folder, url
    else:
        db.add(
            OrcaProject(
                project_id=job.project_id, label=repo.folder, repository_url=url
            )
        )
    repo.state = "linked"
    if verified:
        key = db.get(ProjectDeployKey, job.project_id)
        key.state = "read_verified"
        key.verified_at = now()
    return "done"


def run_one(engine, child):
    from sqlalchemy.orm import Session
    from .models import Event

    with Session(engine) as db:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
        for old in db.scalars(
            select(ProjectJob).where(
                ProjectJob.state == "running", ProjectJob.started < cutoff
            )
        ):
            old.state = "failed"
            old.finished = now()
            old.detail = "중단된 작업입니다. 설정을 확인하고 다시 요청하세요."
        db.commit()
        job = db.scalar(
            select(ProjectJob)
            .where(ProjectJob.state == "pending")
            .order_by(ProjectJob.id)
            .with_for_update(skip_locked=True)
        )
        if not job:
            return False
        job.state = "running"
        job.started = now()
        db.commit()
        identity = job.id
        try:
            state = process(db, job, child)
            job = db.get(ProjectJob, identity)
            if job.state != "cancelled":
                job.state = state
                job.finished = now()
                job.detail = {
                    "done": "고정 작업 완료. 쓰기 권한은 실제 push로 별도 확인하세요.",
                    "waiting_key": "비공개/접근 제한 저장소는 공개키 등록 후 다시 연결하세요.",
                    "failed": "연결 실패. 키 등록과 네트워크를 확인하세요.",
                }[state]
            db.commit()
        except Exception:
            db.rollback()
            job = db.get(ProjectJob, identity)
            if job and job.state != "cancelled":
                job.state = "failed"
                job.finished = now()
                job.detail = (
                    "작업 실패 또는 소유권 변경. 설정을 확인한 뒤 다시 요청하세요."
                )
                repo = db.get(ProjectRepository, job.project_id)
                key = db.get(ProjectDeployKey, job.project_id)
                if (
                    repo
                    and repo.revision == job.revision
                    and key
                    and job.kind == "key_create"
                ):
                    key.state = "failed"
            db.commit()
        return True
