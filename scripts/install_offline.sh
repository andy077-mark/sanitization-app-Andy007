#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d wheels ]]; then
  echo "ERROR: wheels/ directory not found. Use the prepared offline bundle." >&2
  exit 1
fi
if [[ ! -f requirements-lock.txt ]]; then
  echo "ERROR: requirements-lock.txt is missing from the offline bundle." >&2
  exit 1
fi
if [[ ! -f RUNTIME_MANIFEST.json ]]; then
  echo "ERROR: RUNTIME_MANIFEST.json is missing from the offline bundle." >&2
  exit 1
fi

python3 - "$ROOT/RUNTIME_MANIFEST.json" <<'PY'
import json
import os
import platform
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text("utf-8"))
values = {}
os_release = Path("/etc/os-release")
if os_release.exists():
    for raw in os_release.read_text("utf-8", errors="ignore").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value.strip().strip('"')

actual_os = values.get("ID", "linux")
actual_version = values.get("VERSION_ID", "unknown")
actual_py = f"{sys.version_info.major}.{sys.version_info.minor}"
actual_arch = platform.machine()
expected = {
    "os_id": manifest.get("os_id"),
    "os_version": manifest.get("os_version"),
    "python_major_minor": manifest.get("python_major_minor"),
    "architecture": manifest.get("architecture"),
}
actual = {
    "os_id": actual_os,
    "os_version": actual_version,
    "python_major_minor": actual_py,
    "architecture": actual_arch,
}
errors = []
for key, expected_value in expected.items():
    if expected_value and str(expected_value) != str(actual[key]):
        errors.append(f"{key}: bundle={expected_value}, host={actual[key]}")
if errors:
    raise SystemExit(
        "ERROR: this offline bundle does not match the target host.\n  "
        + "\n  ".join(errors)
        + "\nDeploy the bundle built for this Ubuntu/Python/architecture combination."
    )
print(
    f"Bundle compatibility OK: {actual_os} {actual_version} / "
    f"Python {actual_py} / {actual_arch}"
)
PY

if [[ -f WHEELS_SHA256SUMS.txt ]]; then
  echo "Verifying bundled wheel checksums..."
  (cd wheels && sha256sum -c ../WHEELS_SHA256SUMS.txt)
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0], "OK")
PY

if ! python3 -m venv --help >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: python3-venv is not available on this host.
Install the matching Ubuntu python3-venv package from approved internal/offline
OS media. The application will not contact Ubuntu or any internet repository.
EOF
  exit 1
fi

rm -rf .venv
python3 -m venv .venv
PIP_NO_INDEX=1 "$ROOT/.venv/bin/python" -m pip install \
  --no-index \
  --find-links="$ROOT/wheels" \
  -r "$ROOT/requirements-lock.txt"

"$ROOT/.venv/bin/python" "$ROOT/scripts/verify_environment.py"

echo
echo "Offline installation completed successfully."
echo "No Python package was downloaded from the internet."
echo "Before production startup, create an administrator:"
echo "  .venv/bin/python main.py --create-user <username> --role admin"
echo
echo "Optional analyst account:"
echo "  .venv/bin/python main.py --create-user <username> --role analyst"
echo
echo "Testing server:"
echo "  .venv/bin/python main.py --serve"
echo
echo "Production deployment: follow DEPLOYMENT.md for Gunicorn + systemd."
