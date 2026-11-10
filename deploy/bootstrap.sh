#!/usr/bin/env bash
set -euo pipefail
umask 027

# Replaced with a fixed UTC deadline by provision.ps1; never reset on reboot.
STOP_AT='__STOP_AT__'
cat > /etc/systemd/system/kosmos-auto-stop.service <<'UNIT'
[Unit]
Description=Stop the EC2 instance after its approved initial run
[Service]
Type=oneshot
ExecStart=/usr/sbin/shutdown -h now
UNIT
cat > /etc/systemd/system/kosmos-auto-stop.timer <<UNIT
[Unit]
Description=Absolute approved shutdown deadline
[Timer]
OnCalendar=${STOP_AT}
Persistent=true
AccuracySec=1s
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now kosmos-auto-stop.timer

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git jq python3 python3-venv sqlite3 unzip dbus-user-session
if ! id orca >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash orca
fi
chmod 700 /home/orca
install -d -o orca -g orca -m 750 /home/orca/projects
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/80-kosmos.conf

ORCA_VERSION=1.4.255
ORCA_SHA256=6df53f4f6c919fd1f10dfe3511940934acc940a7754eb1b0e896d2c62e4add5a
curl --fail --location --retry 3 --output /var/tmp/orca.deb \
  "https://github.com/stablyai/orca/releases/download/v${ORCA_VERSION}/orca-ide_${ORCA_VERSION}_amd64.deb"
printf '%s  %s\n' "$ORCA_SHA256" /var/tmp/orca.deb | sha256sum --check -
apt-get install -y /var/tmp/orca.deb
rm /var/tmp/orca.deb
loginctl enable-linger orca
ORCA_UID=$(id -u orca)
systemctl start "user@${ORCA_UID}.service"
runuser -u orca -- env XDG_RUNTIME_DIR="/run/user/${ORCA_UID}" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${ORCA_UID}/bus" \
  orca-ide serve service install --port 6768 --bind 0.0.0.0 \
  --refuse-public --pairing-address 127.0.0.1 --json
install -d -m 750 /var/lib/kosmos
date -u --iso-8601=seconds > /var/lib/kosmos/bootstrap-completed
