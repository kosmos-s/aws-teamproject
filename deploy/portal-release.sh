#!/bin/bash
# Operator/SSM only. Never wired to a web endpoint. No secret values are printed.
set -euo pipefail
archive=$(realpath -- "${1:?release archive required}")
root=/opt/kosmos-portal
backup=/var/tmp/kosmos-before-review-$(date -u +%Y%m%dT%H%M%SZ).tgz
cd "$root"

# Verify a known baseline and an exact safe file inventory before any mutation.
python3 - "$archive" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1]) as package:
    manifest=json.load(package.extractfile('release-manifest.json'))
    expected=set(manifest['files'])|{'release-manifest.json'}
    members=package.getmembers()
    if {m.name for m in members}!=expected or any(not m.isfile() for m in members):raise SystemExit('Invalid release inventory')
    for name,digest in manifest['base'].items():
        p=Path(name)
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=digest:
            raise SystemExit('Baseline mismatch; deployment refused')
    for name,digest in manifest['files'].items():
        if name.startswith('/') or '..' in Path(name).parts or not name.startswith(('app/','deploy/','requirements.')):raise SystemExit('Invalid release path')
        if hashlib.sha256(package.extractfile(name).read()).hexdigest()!=digest:raise SystemExit('Release checksum mismatch')
print('Baseline and release checksums verified')
PY
curl -fsS http://127.0.0.1:8000/health >/dev/null
stage=$(mktemp -d /var/tmp/kosmos-review-release.XXXXXX)
chmod 755 "$stage"
tar -xzf "$archive" -C "$stage"
# Existing locked dependencies are unchanged; install the added crypto dependency before stopping anything.
.venv/bin/python -m pip install --disable-pip-version-check -r "$stage/requirements.lock" >/dev/null
tar -czf "$backup" app requirements.lock
chmod 600 "$backup"

as_portal() {
  systemd-run --quiet --wait --pipe --collect --unit="kosmos-release-$(date +%s%N)" \
    -p User=kosmos-portal -p Group=kosmos-portal -p WorkingDirectory="$root" \
    -p EnvironmentFile=/etc/kosmos-portal.env \
    "$root/.venv/bin/python" "$@"
}

switched=0
timers=()
for unit in kosmos-monitor.timer kosmos-backup.timer kosmos-orca-link.timer; do
  if systemctl is-active --quiet "$unit"; then timers+=("$unit"); fi
done
resume_timers() {
  if [[ ${#timers[@]} -gt 0 ]]; then systemctl start "${timers[@]}"; fi
}
rollback() {
  result=$?
  trap - ERR
  systemctl stop kosmos-portal || true
  if [[ "$switched" == 1 ]]; then
    if ! as_portal "$stage/deploy/totp-compat.py" --restore-legacy; then
      echo 'Compatibility rollback refused; old code was not restored. Operator recovery required.'
      exit 8
    fi
    tar -xzf "$backup" -C "$root"
  fi
  systemctl start kosmos-portal || true
  resume_timers || true
  echo 'Release failed; prior code restored after factor compatibility check.'
  exit "$result"
}
trap rollback ERR
if [[ ${#timers[@]} -gt 0 ]]; then systemctl stop "${timers[@]}"; fi
systemctl stop kosmos-monitor.service kosmos-backup.service kosmos-orca-link.service
systemctl stop kosmos-portal
switched=1
python3 - "$archive" <<'PY'
import sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1]) as package:
    for m in package.getmembers():
        if m.name=='release-manifest.json':continue
        p=Path(m.name);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(package.extractfile(m).read());p.chmod(0o644)
PY
as_portal -c 'from app.main import create_app; a=create_app(); a.state.engine.dispose()'
as_portal deploy/totp-compat.py --check
as_portal deploy/verify-release.py
systemctl start kosmos-portal
healthy=0
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then healthy=1; break; fi
  sleep 1
done
[[ "$healthy" == 1 ]]
[[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/projects)" == 401 ]]
resume_timers
trap - ERR
echo 'Release installed; health and anonymous denial verified. Shutdown timers unchanged.'
