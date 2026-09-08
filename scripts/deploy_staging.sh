#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${SANIT_APP_DIR:-/opt/sanitization-app}"
SERVICE_NAME="sanitization-app"
SERVICE_USER="${SANIT_SERVICE_USER:-sanitizer}"
SERVICE_GROUP="${SANIT_SERVICE_GROUP:-sanitizer}"
ENV_DIR="/etc/sanitization-app"
ENV_FILE="$ENV_DIR/sanitization.env"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALLOW_ONLINE=0
ADMIN_USER=""

usage() {
  cat <<'EOF'
Usage: sudo bash scripts/deploy_staging.sh [options]

Options:
  --online                Allow pip to install from configured package indexes
                          when a local wheels/ directory is not present.
  --admin USERNAME        Create the first administrator during deployment.
                          Password is prompted securely and is never put on the
                          command line or written to the environment file.
  --app-dir PATH          Installation directory (default: /opt/sanitization-app)
  --help                  Show this help.

Secure default: if wheels/ exists, installation is offline with --no-index.
Without wheels/, the script refuses network package access unless --online is
explicitly supplied.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --online) ALLOW_ONLINE=1; shift ;;
    --admin) ADMIN_USER="${2:-}"; [[ -n "$ADMIN_USER" ]] || { echo "ERROR: --admin needs a username" >&2; exit 2; }; shift 2 ;;
    --app-dir) APP_DIR="${2:-}"; [[ -n "$APP_DIR" ]] || { echo "ERROR: --app-dir needs a path" >&2; exit 2; }; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR: run this script as root, for example:" >&2
  echo "  sudo bash scripts/deploy_staging.sh --admin socadmin --online" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_DIR/main.py" || ! -f "$SOURCE_DIR/deploy/sanitization-app.service" ]]; then
  echo "ERROR: run this script from the Sanitization App repository/bundle." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0], "OK")
PY

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "ERROR: python3-venv is required. Install it from your approved Ubuntu repository/media." >&2
  exit 1
fi

if ! getent group "$SERVICE_GROUP" >/dev/null 2>&1; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$ENV_DIR"

# Stop an existing service before updating application files.
if systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
  systemctl stop "$SERVICE_NAME.service" || true
fi

# Preserve runtime state on upgrades. Copy application code/configuration only.
for entry in main.py wsgi.py bad_words.txt requirements.txt README.md DEPLOYMENT.md gunicorn.conf.py templates sanitization_v2 scripts deploy tools; do
  [[ -e "$SOURCE_DIR/$entry" ]] || continue
  rm -rf "$APP_DIR/$entry"
  cp -a "$SOURCE_DIR/$entry" "$APP_DIR/$entry"
done

# Copy an offline wheelhouse when supplied in a release bundle.
if [[ -d "$SOURCE_DIR/wheels" ]]; then
  rm -rf "$APP_DIR/wheels"
  cp -a "$SOURCE_DIR/wheels" "$APP_DIR/wheels"
fi

mkdir -p "$APP_DIR"/{uploads,outputs,logs,temp,data,certs}
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"
chmod 0750 "$APP_DIR"
chmod 0700 "$APP_DIR"/{uploads,outputs,logs,temp,data,certs}

rm -rf "$APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"

if [[ -d "$APP_DIR/wheels" ]]; then
  echo "Installing Python packages from local offline wheelhouse..."
  "$APP_DIR/.venv/bin/python" -m pip install --no-index --find-links="$APP_DIR/wheels" -r "$APP_DIR/requirements.txt"
elif [[ "$ALLOW_ONLINE" -eq 1 ]]; then
  echo "Installing Python packages from configured package indexes (--online explicitly enabled)..."
  "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
else
  cat >&2 <<EOF
ERROR: no local wheels/ directory was found.
For an air-gapped installation, deploy the tested offline artifact.
For an internet-connected staging VM only, rerun with --online.
EOF
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$APP_DIR/deploy/sanitization.env.example" "$ENV_FILE"
  # Use a persistent high-entropy Flask signing key owned by root.
  SECRET="$($APP_DIR/.venv/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  printf '\nSANIT_SECRET_KEY=%s\n' "$SECRET" >> "$ENV_FILE"
fi
chown root:"$SERVICE_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

# Ensure local test TLS material exists before service confinement is applied.
su -s /bin/bash -c "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' -c 'from sanitization_v2 import config as c; c.ensure_selfsigned_certs()'" "$SERVICE_USER"

# Create the initial administrator before the systemd preflight requires one.
if [[ -n "$ADMIN_USER" ]]; then
  if ! su -s /bin/bash -c "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' main.py --list-users" "$SERVICE_USER" | grep -Eq '^.+[[:space:]]+admin[[:space:]]+yes'; then
    echo
    echo "Creating initial administrator: $ADMIN_USER"
    echo "You will be prompted for the password twice."
    su -s /bin/bash -c "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' main.py --create-user '$ADMIN_USER' --role admin" "$SERVICE_USER"
  else
    echo "An enabled administrator already exists; skipping administrator creation."
  fi
fi

# Refuse to install/start a production-style service without an administrator.
if ! su -s /bin/bash -c "cd '$APP_DIR' && '$APP_DIR/.venv/bin/python' main.py --list-users" "$SERVICE_USER" | grep -Eq '^.+[[:space:]]+admin[[:space:]]+yes'; then
  cat >&2 <<EOF
ERROR: no enabled administrator exists.
Create one and rerun this installer, for example:
  sudo -u $SERVICE_USER $APP_DIR/.venv/bin/python $APP_DIR/main.py --create-user socadmin --role admin
EOF
  exit 1
fi

install -o root -g root -m 0644 "$APP_DIR/deploy/sanitization-app.service" "/etc/systemd/system/$SERVICE_NAME.service"

# Verify the exact installed runtime as the restricted service account.
su -s /bin/bash -c "cd '$APP_DIR' && SANIT_REQUIRE_ADMIN=1 '$APP_DIR/.venv/bin/python' scripts/verify_environment.py" "$SERVICE_USER"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"
systemctl restart "$SERVICE_NAME.service"

sleep 2
if ! systemctl is-active --quiet "$SERVICE_NAME.service"; then
  echo "ERROR: $SERVICE_NAME failed to start." >&2
  systemctl status "$SERVICE_NAME.service" --no-pager >&2 || true
  journalctl -u "$SERVICE_NAME.service" -n 80 --no-pager >&2 || true
  exit 1
fi

if ! curl -kfsS --max-time 10 https://127.0.0.1:8443/healthz >/dev/null; then
  echo "ERROR: service is running but HTTPS /healthz did not respond successfully." >&2
  journalctl -u "$SERVICE_NAME.service" -n 80 --no-pager >&2 || true
  exit 1
fi

echo
echo "============================================================"
echo "SOC Data Sanitization Platform staging deployment: SUCCESS"
echo "============================================================"
echo "Application: $APP_DIR"
echo "Service:     $SERVICE_NAME.service"
echo "Health:      https://127.0.0.1:8443/healthz"
echo
echo "Next: run the browser/API acceptance checker as an Admin and Analyst:"
echo "  $APP_DIR/.venv/bin/python $APP_DIR/scripts/staging_acceptance.py --url https://127.0.0.1:8443 --username <user> --role admin"
echo "  $APP_DIR/.venv/bin/python $APP_DIR/scripts/staging_acceptance.py --url https://127.0.0.1:8443 --username <user> --role analyst"
