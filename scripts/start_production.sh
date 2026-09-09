#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 scripts/check_bundle_compatibility.py "$ROOT/RUNTIME_MANIFEST.json"

if [ ! -x ".venv/bin/gunicorn" ]; then
  echo "Gunicorn is not installed in .venv. Deploy the matching tested offline bundle first."
  exit 1
fi

.venv/bin/python scripts/verify_environment.py
exec .venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
