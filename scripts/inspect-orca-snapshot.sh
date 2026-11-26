#!/usr/bin/env bash
# Read-only host preflight. No environment, credentials, IDs or file contents are printed.
set -u
app=/opt/kosmos-portal
unit=kosmos-orca-link.service
unit_file=/etc/systemd/system/$unit
checks_failed=0
all_before=1
all_after=1

check_hash() {
  local label=$1 path=$2 before=$3 after=$4 actual
  if [[ ! -f "$path" || -L "$path" || ! -r "$path" ]] || ! actual=$(sha256sum -- "$path"); then
    printf '%s: missing, unreadable, or symlink\n' "$label"
    checks_failed=1
    all_before=0
    all_after=0
    return
  fi
  actual=${actual%% *}
  case "$actual" in
    "$before") printf '%s: baseline\n' "$label"; all_after=0 ;;
    "$after") printf '%s: candidate\n' "$label"; all_before=0 ;;
    *) printf '%s: differs from both baseline and candidate\n' "$label"
       checks_failed=1; all_before=0; all_after=0 ;;
  esac
}

printf 'checked_at_kst: %s\n' "$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S %Z')"
if [[ "$(systemctl show -p FragmentPath --value "$unit" 2>/dev/null)" != "$unit_file" ]] ||
   ! dropins=$(systemctl show -p DropInPaths --value "$unit" 2>/dev/null) || [[ -n "$dropins" ]]; then
  printf 'unit: unexpected active location or overrides; operator review required\n'
  checks_failed=1
fi
check_hash app_config "$app/app/config.py" 87d8617dcf99868249cfe6b4d44396d85cc916ebc2ec897edc699b05cd2dcaea 87cfc0b8b83a298bbe31115eaf4337d394014708959d715424eb0855c5fa7a2a
check_hash app_orca_admin "$app/app/orca_admin.py" 887a9a02af35a403d37a4c8036c34c8a1b5a92f5123459350dbf85c85f7fd187 b0d05bc513d41f2ae456ceb106fb0cb50643d3db7118df796c4dcea4fe8e88ee
check_hash worker "$app/deploy/orca-link-worker.py" ea2fef6526e5a7d5c3d8c8f75c2749d51272fe55cd8c72058535068fde0d5da6 f9d608721086d68b18232651fa0bb759d0a51fe44ea0282ea1d4517d04bd55e5
check_hash installed_unit "$unit_file" 11b3649d098345a1ac9d2e384e68f070076d0570e37143d91e73b8d67c4e53d9 57088f1211f0594cc2d1f1da4b87c0d344f11bf59b55257ba24967654bd301a7

for service in kosmos-portal.service kosmos-orca-link.timer; do
  state=$(systemctl is-active "$service" 2>/dev/null) || checks_failed=1
  printf '%s: %s\n' "$service" "${state:-unknown}"
done
TZ=Asia/Seoul systemctl list-timers --all --no-pager kosmos-auto-stop.timer kosmos-rds-stop.timer || checks_failed=1

health=$(curl --silent --max-time 5 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8000/health) || checks_failed=1
printf 'local_health_http: %s\n' "$health"
[[ "$health" == 200 ]] || checks_failed=1

if (( all_after )); then
  stat --format='snapshot_dir: %U:%G %a %F' /run/kosmos-orca-link || checks_failed=1
  stat --format='snapshot_file: %U:%G %a %F' /run/kosmos-orca-link/orca-folders.json || checks_failed=1
  [[ "$(stat -c '%U:%G %a %F' /run/kosmos-orca-link 2>/dev/null)" == 'root:kosmos-portal 750 directory' ]] || checks_failed=1
  [[ "$(stat -c '%U:%G %a %F' /run/kosmos-orca-link/orca-folders.json 2>/dev/null | cut -d' ' -f1-2)" == 'root:kosmos-portal 640' &&
     -f /run/kosmos-orca-link/orca-folders.json && ! -L /run/kosmos-orca-link/orca-folders.json ]] || checks_failed=1
  if runuser -u kosmos-portal -- test -r /run/kosmos-orca-link/orca-folders.json &&
     runuser -u kosmos-portal -- test ! -w /run/kosmos-orca-link &&
     runuser -u kosmos-portal -- test ! -w /run/kosmos-orca-link/orca-folders.json; then
    printf 'portal_snapshot_access: read OK, write denied\n'
  else
    printf 'portal_snapshot_access: REVIEW_REQUIRED\n'
    checks_failed=1
  fi
fi

if (( checks_failed )); then
  printf 'preflight: REVIEW_REQUIRED\n'
  exit 2
elif (( all_before )); then
  printf 'preflight: BASELINE_MATCH\n'
elif (( all_after )); then
  printf 'preflight: CANDIDATE_MATCH\n'
else
  printf 'preflight: MIXED_RELEASE_REVIEW_REQUIRED\n'
  exit 2
fi
