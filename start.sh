#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment is missing. Install dependencies first."
  echo "Online staging:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  echo "Air-gapped:      bash scripts/install_offline.sh"
  exit 1
fi

exec .venv/bin/python main.py --serve
