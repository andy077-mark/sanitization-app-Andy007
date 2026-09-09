#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="$(uname -m)"
DIST="$ROOT/dist"

OS_ID="linux"
OS_VERSION="unknown"
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-linux}"
  OS_VERSION="${VERSION_ID:-unknown}"
fi
PYTHON_MM="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
OS_LABEL="$(printf '%s' "$OS_ID" | sed 's/^./\U&/')${OS_VERSION}"
BUNDLE_ID="${OS_LABEL}-Python${PYTHON_MM}-${ARCH}"
STAGE="$DIST/SanitizationApp-v2.1-${BUNDLE_ID}-offline"
ARCHIVE="$DIST/SanitizationApp-v2.1-${BUNDLE_ID}-offline.tar.gz"
LOCK_FILE="$ROOT/requirements-lock.txt"

if [[ ! -f "$LOCK_FILE" ]]; then
  echo "ERROR: complete dependency lock not found: $LOCK_FILE" >&2
  exit 1
fi

rm -rf "$STAGE" "$ARCHIVE" "$ARCHIVE.sha256"
mkdir -p "$STAGE/wheels" "$STAGE/scripts"

echo "Building offline Python wheelhouse for ${OS_ID} ${OS_VERSION} / Python ${PYTHON_MM} / ${ARCH}..."
python3 -m pip download \
  --only-binary=:all: \
  -r "$LOCK_FILE" \
  -d "$STAGE/wheels"

cp "$ROOT/main.py" "$STAGE/"
cp "$ROOT/wsgi.py" "$STAGE/"
cp "$ROOT/gunicorn.conf.py" "$STAGE/"
cp "$ROOT/bad_words.txt" "$STAGE/"
cp "$ROOT/requirements.txt" "$STAGE/"
cp "$ROOT/requirements-lock.txt" "$STAGE/"
cp "$ROOT/README.md" "$STAGE/"
[[ -f "$ROOT/DEPLOYMENT.md" ]] && cp "$ROOT/DEPLOYMENT.md" "$STAGE/"
[[ -f "$ROOT/PERFORMANCE_BENCHMARK.md" ]] && cp "$ROOT/PERFORMANCE_BENCHMARK.md" "$STAGE/"
[[ -f "$ROOT/OS_COMPATIBILITY_REVIEW.md" ]] && cp "$ROOT/OS_COMPATIBILITY_REVIEW.md" "$STAGE/"
[[ -f "$ROOT/start.sh" ]] && cp "$ROOT/start.sh" "$STAGE/"
[[ -f "$ROOT/start.bat" ]] && cp "$ROOT/start.bat" "$STAGE/"
cp -R "$ROOT/templates" "$STAGE/"
cp -R "$ROOT/sanitization_v2" "$STAGE/"
cp -R "$ROOT/deploy" "$STAGE/"
cp "$ROOT/scripts/install_offline.sh" "$STAGE/scripts/"
cp "$ROOT/scripts/verify_environment.py" "$STAGE/scripts/"
cp "$ROOT/scripts/check_bundle_compatibility.py" "$STAGE/scripts/"
cp "$ROOT/scripts/start_production.sh" "$STAGE/scripts/"
cp "$ROOT/scripts/deploy_staging.sh" "$STAGE/scripts/"
cp "$ROOT/scripts/staging_acceptance.py" "$STAGE/scripts/"
cp "$ROOT/scripts/benchmark_performance.py" "$STAGE/scripts/"

chmod +x "$STAGE/scripts/"*.sh "$STAGE/scripts/"*.py

if [[ -n "${SANIT_7ZIP_BINARY:-}" ]]; then
  if [[ ! -f "$SANIT_7ZIP_BINARY" ]]; then
    echo "ERROR: SANIT_7ZIP_BINARY does not point to a file: $SANIT_7ZIP_BINARY" >&2
    exit 1
  fi
  mkdir -p "$STAGE/tools/7zip"
  cp "$SANIT_7ZIP_BINARY" "$STAGE/tools/7zip/7zz"
  chmod +x "$STAGE/tools/7zip/7zz"
  echo "Bundled supplied 7-Zip binary: $SANIT_7ZIP_BINARY"
else
  echo "NOTE: no 7-Zip binary bundled. Set SANIT_7ZIP_BINARY=/path/to/7zz when building"
  echo "      if the air-gapped target needs .7z/.rar support."
fi

(
  cd "$STAGE/wheels"
  sha256sum * > ../WHEELS_SHA256SUMS.txt
)

python3 - "$STAGE" "$OS_ID" "$OS_VERSION" "$PYTHON_MM" "$ARCH" <<'PY'
import json
import platform
import subprocess
import sys
from pathlib import Path

stage = Path(sys.argv[1])
os_id, os_version, python_mm, arch = sys.argv[2:]
try:
    commit = subprocess.check_output(
        ["git", "-C", str(stage.parent.parent), "rev-parse", "HEAD"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
except Exception:
    commit = "unknown"

lock = stage / "requirements-lock.txt"
locked = []
for raw in lock.read_text("utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "==" not in line:
        continue
    name, version = line.split("==", 1)
    locked.append({"name": name, "version": version})

manifest = {
    "application": "SOC Data Sanitization Platform",
    "version": "2.1",
    "commit": commit,
    "os_id": os_id,
    "os_version": os_version,
    "python_major_minor": python_mm,
    "python_build": platform.python_version(),
    "architecture": arch,
    "dependency_lock": "requirements-lock.txt",
    "dependencies": locked,
    "network_required_on_target": False,
}
(stage / "RUNTIME_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

cat > "$STAGE/OFFLINE_INSTALL.txt" <<EOF
SOC Data Sanitization Platform v2.1 - Offline Installation

Bundle target:
  OS:           ${OS_ID} ${OS_VERSION}
  Python:       ${PYTHON_MM}
  Architecture: ${ARCH}

Recommended staging/systemd installation:

  sudo bash scripts/deploy_staging.sh --admin <username>

The staging deployer automatically uses the included wheels/ directory with
--no-index. It does not contact PyPI or any external Python package repository.
The target OS must provide its normal system Python ${PYTHON_MM} and python3-venv
package. If those OS packages are managed offline, obtain them from the approved
internal Ubuntu repository/media before deployment.

After deployment, create an Analyst if required:

  sudo -u sanitizer /opt/sanitization-app/.venv/bin/python /opt/sanitization-app/main.py --create-user analyst01 --role analyst

Then run acceptance as both roles:

  /opt/sanitization-app/.venv/bin/python /opt/sanitization-app/scripts/staging_acceptance.py --url https://127.0.0.1:8443 --username <admin> --role admin
  /opt/sanitization-app/.venv/bin/python /opt/sanitization-app/scripts/staging_acceptance.py --url https://127.0.0.1:8443 --username <analyst> --role analyst

Performance baseline after staging acceptance:

  sudo -u sanitizer /opt/sanitization-app/.venv/bin/python /opt/sanitization-app/scripts/benchmark_performance.py --sizes-mb 100 500

Alternative manual installation:

  PIP_NO_INDEX=1 bash scripts/install_offline.sh
  .venv/bin/python main.py --create-user <username> --role admin

The offline installer uses only the local wheels/ directory. ZIP/TAR/GZ/BZ2/XZ
work without 7-Zip. .7z/.rar require a bundled or locally installed 7-Zip binary.
EOF

mkdir -p "$DIST"
tar -C "$DIST" -czf "$ARCHIVE" "$(basename "$STAGE")"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"

echo
echo "Offline bundle created:"
echo "  $ARCHIVE"
echo "Checksum:"
cat "$ARCHIVE.sha256"
