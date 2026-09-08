#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d wheels ]]; then
  echo "ERROR: wheels/ directory not found. Use the prepared offline bundle." >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0], "OK")
PY

python3 -m venv .venv
"$ROOT/.venv/bin/python" -m pip install \
  --no-index \
  --find-links="$ROOT/wheels" \
  -r "$ROOT/requirements.txt"

"$ROOT/.venv/bin/python" "$ROOT/scripts/verify_environment.py"

echo
echo "Offline installation completed successfully."
echo "Start for testing with:"
echo "  .venv/bin/python main.py --serve"
