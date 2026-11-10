#!/usr/bin/env bash
set -euo pipefail

expected=https://github.com/kosmos-s/aws-teamproject.git
target="${1:-$HOME/projects/aws-teamproject}"
if [[ "$target" != /* ]]; then
  echo 'Use an absolute destination path.' >&2
  exit 2
fi
if [[ -e "$target" ]]; then
  if [[ ! -d "$target/.git" ]]; then
    echo 'Destination exists and is not a Git checkout; refusing to overwrite it.' >&2
    exit 2
  fi
  actual=$(git -C "$target" remote get-url origin)
  if [[ "$actual" != "$expected" ]]; then
    echo 'Destination belongs to another remote; refusing to alter it.' >&2
    exit 2
  fi
else
  mkdir -p "$(dirname "$target")"
  git clone "$expected" "$target"
fi
command -v orca-ide >/dev/null
orca-ide repo add --path "$target" --json
git -C "$target" status --short --branch
printf 'Registered project: %s\n' "$target"
