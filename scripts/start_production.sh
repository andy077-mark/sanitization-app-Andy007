#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/gunicorn" ]; then
  echo "Gunicorn is not installed in .venv. Install the pinned runtime dependencies first."
  exit 1
fi

.venv/bin/python scripts/verify_environment.py
exec .venv/bin/gunicorn --config gunicorn.conf.py wsgi:application
