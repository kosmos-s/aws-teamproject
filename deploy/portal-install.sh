#!/usr/bin/env bash
set -euo pipefail
# Run as root after copying the reviewed release to /opt/kosmos-portal.
test -f /opt/kosmos-portal/requirements.txt
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv nginx certbot python3-certbot-nginx
id kosmos-portal >/dev/null 2>&1 || useradd --system --home /var/lib/kosmos-portal --create-home --shell /usr/sbin/nologin kosmos-portal
install -d -o kosmos-portal -g kosmos-portal -m 700 /var/lib/kosmos-portal
python3 -m venv /opt/kosmos-portal/.venv
/opt/kosmos-portal/.venv/bin/pip install --disable-pip-version-check -r /opt/kosmos-portal/requirements.lock
install -m 644 /opt/kosmos-portal/deploy/kosmos-portal.service /etc/systemd/system/
for type in monitor backup; do
  install -m 644 "/opt/kosmos-portal/deploy/kosmos-${type}.service" /etc/systemd/system/
  install -m 644 "/opt/kosmos-portal/deploy/kosmos-${type}.timer" /etc/systemd/system/
done
systemctl daemon-reload
echo 'Install complete. Supply /etc/kosmos-portal.env (0600), configure HTTPS, then enable services.'
