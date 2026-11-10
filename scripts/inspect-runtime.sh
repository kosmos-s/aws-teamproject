#!/usr/bin/env bash
set -u
echo '=== bootstrap ==='
cloud-init status
test -f /var/lib/kosmos/bootstrap-completed && cat /var/lib/kosmos/bootstrap-completed
echo '=== shutdown timer ==='
systemctl list-timers kosmos-auto-stop.timer --all --no-pager
echo '=== packages ==='
dpkg-query -W -f='${Package} ${Version}\n' orca-ide 2>/dev/null || true
echo '=== system resources ==='
free -m
df -h /
echo '=== runtime ==='
if id orca >/dev/null 2>&1; then
  uid=$(id -u orca)
  runuser -u orca -- env XDG_RUNTIME_DIR="/run/user/$uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" orca-ide serve service status --json || true
fi
ss -lntp | head -20
if [ -f /var/lib/kosmos/bootstrap-completed ]; then
  echo '=== http ==='
  curl --silent --max-time 10 --output /var/tmp/kosmos-index.html --write-out 'Root HTTP %{http_code}\n' http://127.0.0.1:6768/
  head -c 250 /var/tmp/kosmos-index.html
  echo
else
  tail -15 /var/log/cloud-init-output.log
fi
