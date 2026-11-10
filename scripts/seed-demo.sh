#!/usr/bin/env bash
set -euo pipefail
uid=$(id -u orca)
runuser -u orca -- env XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" bash -s <<'USER'
set -euo pipefail
demo=/home/orca/projects/kosmos-demo
if [ -e "$demo" ]; then
  echo 'Demo already exists; refusing to overwrite it.' >&2
  exit 1
fi
mkdir -p "$demo"
cd "$demo"
git init --initial-branch=main
git config user.name 'KOSMOS Demo'
git config user.email 'demo@localhost'
printf '# KOSMOS AWS Demo\n\nRun: python3 main.py\n' > README.md
printf 'print("Hello from AWS EC2")\n' > main.py
git add README.md main.py
git commit -m 'Initialize AWS Orca demonstration project'
orca-ide repo add --path "$demo" --json
orca-ide worktree list --repo "path:$demo" --json
USER
