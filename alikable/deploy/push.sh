#!/usr/bin/env bash
# Copy this project from your laptop to the server, and restart the app if it is set up.
#
#   deploy/push.sh <server ip> <ssh key file>
#
# Copies the working tree as it is now (uncommitted changes included). Never copies .env,
# .venv or output/: the server keeps its own keys, environment and projects. A restart stops
# any crew job that is running, so push when no build is in progress.
set -euo pipefail

HOST="${1:?usage: push.sh <server ip> <ssh key file>}"
KEY="${2:?usage: push.sh <server ip> <ssh key file>}"
APP=/opt/alikable-crew/alikable
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "ubuntu@$HOST")

"${SSH[@]}" "sudo mkdir -p $APP"
rsync -az --delete --rsync-path="sudo rsync" -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  --exclude .env --exclude .venv --exclude output/ --exclude .crewai/ --exclude .gradio/ \
  --exclude __pycache__/ --exclude .DS_Store \
  "$LOCAL/" "ubuntu@$HOST:$APP/"

# Before setup.sh has run there is no alikable user or service yet: setup.sh does the rest
"${SSH[@]}" "if id alikable >/dev/null 2>&1 && [ -f /etc/systemd/system/alikable.service ]; then
  sudo chown -R alikable:alikable /opt/alikable-crew &&
  sudo -u alikable -H bash -c 'cd $APP && ~/.local/bin/uv sync --frozen' &&
  sudo cp $APP/deploy/alikable.service /etc/systemd/system/alikable.service &&
  sudo systemctl daemon-reload && sudo systemctl restart alikable &&
  echo 'Pushed and restarted.'
else
  echo 'Copied. Now run: sudo $APP/deploy/setup.sh'
fi"
