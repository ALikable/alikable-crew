#!/usr/bin/env bash
# Pull the latest code onto the server and restart the app.
#
#   sudo /opt/alikable-crew/alikable/deploy/update.sh
#
# A restart stops any crew job that is running, so update when no build is in progress.
set -euo pipefail

APP=/opt/alikable-crew/alikable
APP_USER=alikable

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

sudo -u "$APP_USER" -H bash -c "cd '$APP' && git pull --ff-only && ~/.local/bin/uv sync --frozen"
cp "$APP/deploy/alikable.service" /etc/systemd/system/alikable.service
systemctl daemon-reload
systemctl restart alikable
systemctl --no-pager status alikable | head -5
