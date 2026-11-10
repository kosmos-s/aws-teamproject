#!/usr/bin/env bash
set -euo pipefail
curl --fail --location --retry 3 -o /var/tmp/codex.tar.gz https://github.com/openai/codex/releases/download/rust-v0.167.0/codex-x86_64-unknown-linux-musl.tar.gz
printf '%s  %s\n' 9d64836106d5b374e90ee4454c7ebcde7ca7106558bd7e41a34b9f26ebda251a /var/tmp/codex.tar.gz | sha256sum --check -
tar -xzf /var/tmp/codex.tar.gz -C /var/tmp codex-x86_64-unknown-linux-musl
install -m 755 /var/tmp/codex-x86_64-unknown-linux-musl /usr/local/bin/codex
rm /var/tmp/codex.tar.gz /var/tmp/codex-x86_64-unknown-linux-musl
runuser -u orca -- codex --version
runuser -u orca -- codex login --help
runuser -u orca -- orca-ide account add --help
