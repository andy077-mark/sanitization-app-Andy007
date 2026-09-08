#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="$(uname -m)"
DIST="$ROOT/dist"
STAGE="$DIST/SanitizationApp-v2.1-offline-${ARCH}"
ARCHIVE="$DIST/SanitizationApp-v2.1-offline-${ARCH}.tar.gz"

rm -rf "$STAGE" "$ARCHIVE" "$ARCHIVE.sha256"
mkdir -p "$STAGE/wheels" "$STAGE/scripts"

echo "Building offline Python wheelhouse for $(python3 --version) / ${ARCH}..."
python3 -m pip download \
  --only-binary=:all: \
  -r "$ROOT/requirements.txt" \
  -d "$STAGE/wheels"

cp "$ROOT/main.py" "$STAGE/"
cp "$ROOT/wsgi.py" "$STAGE/"
cp "$ROOT/gunicorn.conf.py" "$STAGE/"
cp "$ROOT/bad_words.txt" "$STAGE/"
cp "$ROOT/requirements.txt" "$STAGE/"
cp "$ROOT/README.md" "$STAGE/"
[[ -f "$ROOT/DEPLOYMENT.md" ]] && cp "$ROOT/DEPLOYMENT.md" "$STAGE/"
[[ -f "$ROOT/start.sh" ]] && cp "$ROOT/start.sh" "$STAGE/"
[[ -f "$ROOT/start.bat" ]] && cp "$ROOT/start.bat" "$STAGE/"
cp -R "$ROOT/templates" "$STAGE/"
cp -R "$ROOT/sanitization_v2" "$STAGE/"
cp -R "$ROOT/deploy" "$STAGE/"
cp "$ROOT/scripts/install_offline.sh" "$STAGE/scripts/"
cp "$ROOT/scripts/verify_environment.py" "$STAGE/scripts/"
cp "$ROOT/scripts/start_production.sh" "$STAGE/scripts/"

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

cat > "$STAGE/OFFLINE_INSTALL.txt" <<'EOF'
SOC Data Sanitization Platform v2.1 - Offline Installation

1. Transfer this entire folder to the air-gapped Ubuntu server.
2. Ensure Python 3.10+ and python3-venv are already installed from approved OS media/repos.
3. Run:

   bash scripts/install_offline.sh

4. Create the first administrator interactively:

   .venv/bin/python main.py --create-user <username> --role admin

5. For production, follow DEPLOYMENT.md to install the systemd/Gunicorn service.

The installer uses only the local wheels/ directory and does not contact PyPI.
ZIP/TAR/GZ/BZ2/XZ can be processed without 7-Zip. .7z/.rar require a bundled or locally installed 7-Zip binary.
EOF

mkdir -p "$DIST"
tar -C "$DIST" -czf "$ARCHIVE" "$(basename "$STAGE")"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"

echo
echo "Offline bundle created:"
echo "  $ARCHIVE"
echo "Checksum:"
cat "$ARCHIVE.sha256"
