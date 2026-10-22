#!/usr/bin/env bash
# One-time setup of Alikable on a fresh Ubuntu 24.04 EC2 instance.
#
#   sudo git clone <your repo URL> /opt/alikable-crew
#   sudo /opt/alikable-crew/alikable/deploy/setup.sh your.domain.com
#
# Installs Node.js 22, Caddy and uv, creates the alikable user, installs the Python
# dependencies, and starts the app behind Caddy with HTTPS for the domain. Safe to run again.
set -euo pipefail

DOMAIN="${1:?usage: setup.sh <domain>}"
REPO=/opt/alikable-crew
APP="$REPO/alikable"
APP_USER=alikable
HERE="$(cd "$(dirname "$0")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ "$HERE" == "$APP/deploy" ]] || { echo "Clone the repo to $REPO first (found the script in $HERE)." >&2; exit 1; }

echo "== System packages"
apt-get update
apt-get install -y curl git ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https

echo "== Node.js 22 (the Code Reviewer's filesystem MCP runs with npx; the build checker uses node --check)"
if ! command -v node >/dev/null || [[ "$(node -v)" != v22* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi
# Installed once, so the first code review doesn't wait for npx to download it
npm install -g @modelcontextprotocol/server-filesystem

echo "== Caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

echo "== App user and files"
id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"
chown -R "$APP_USER:$APP_USER" "$REPO"
git config --system --add safe.directory "$REPO"

echo "== uv and Python dependencies"
sudo -u "$APP_USER" -H bash -c 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u "$APP_USER" -H bash -c "cd '$APP' && ~/.local/bin/uv sync --frozen"

echo "== .env"
if [[ ! -f "$APP/.env" ]]; then
  cp "$HERE/env.example" "$APP/.env"
  NEW_ENV=1
fi
chown "$APP_USER:$APP_USER" "$APP/.env"
chmod 600 "$APP/.env"

echo "== systemd service"
cp "$HERE/alikable.service" /etc/systemd/system/alikable.service
systemctl daemon-reload
systemctl enable alikable

echo "== Caddy site for $DOMAIN"
sed "s/alikable.example.com/$DOMAIN/" "$HERE/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

if [[ -n "${NEW_ENV:-}" ]]; then
  cat <<EOF

Almost done. Fill in $APP/.env (OPENAI_API_KEY, MODEL, ALIKABLE_USER, ALIKABLE_PASSWORD):
  sudo -u $APP_USER nano $APP/.env
then start the app:
  sudo systemctl start alikable
EOF
else
  systemctl restart alikable
  echo
  echo "Running. Open https://$DOMAIN   (logs: journalctl -u alikable -f)"
fi
