# SOC Data Sanitization Platform v2.1 - Production Deployment & Validation

## Validated Ubuntu targets

Automated compatibility validation covers:

- Ubuntu 22.04 with system Python 3.10
- Ubuntu 24.04 with system Python 3.12

The workflow creates a clean virtual environment, installs pinned Python dependencies, verifies the local OCR engine, runs authentication/RBAC and functional smoke tests, validates Gunicorn, and proves the offline Python wheelhouse installation.

## Access model

v2.1 uses local application accounts stored as password hashes in `data/jobs.db`.

### Analyst

- Sign in/out
- Upload files and folders
- Sanitize logs, documents, supported images and archives
- Monitor processing and view history
- Download sanitized outputs and Excel reports
- View active-rule count

### Administrator

Includes all Analyst permissions plus Rules Library administration.

## Output modes

### Direct single-file output

Exactly one file selected directly with **Browse Files** returns a direct sanitized file plus a separate Excel report.

```text
security.log
        ↓
security_SANITIZED.log
Sanitization_Report_<job_id>.xlsx
```

The same behavior applies to supported PDF, DOCX and raster image files.

### Folder / multi-file batch output

Multiple files or **Browse Folder** returns one ZIP preserving the relative hierarchy.

```text
Sanitized_Package_<job_id>.zip
├── Sanitized_Files/
│   └── Case-01/
│       ├── screenshot.png
│       ├── report.pdf
│       └── Logs/
│           └── security.log
└── Sanitization_Report_<job_id>.xlsx
```

A folder upload remains a batch job even when the folder contains only one file.

## Excel audit behavior

Every successful job creates `Sanitization_Report_<job_id>.xlsx` with **Summary** and **Audit** sheets.

Audit columns:

- **File Name**
- **Match Type**
- **Occurrences**
- **Location** — line, spreadsheet cell, PDF page/OCR image, DOCX paragraph/image, filename or path where available
- **Keywords** — configured Rules Library keyword/regular expression

The **Keywords** field is intentionally stored unsanitized so analysts can see which configured rule triggered. The report does not reconstruct the original source match beyond the configured rule text.

## Offline OCR architecture

OCR is performed locally with Tesseract. The application does not call cloud OCR services and does not download an OCR engine at runtime.

OCR is used for:

- standalone `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp`,
- raster/scanned image regions inside PDFs,
- supported raster images embedded in DOCX files.

Matches are mapped back to their image/page coordinates and permanently overwritten. Standalone image metadata is stripped when the sanitized image is re-saved.

### OCR configuration

Production defaults in `deploy/sanitization.env.example`:

```text
SANIT_REQUIRE_OCR=1
SANIT_OCR_LANG=eng
SANIT_OCR_DPI=200
SANIT_OCR_PSM=6
SANIT_OCR_MIN_CONFIDENCE=0
SANIT_OCR_TIMEOUT_SECONDS=120
SANIT_MAX_IMAGE_PIXELS=120000000
```

Optional explicit local paths:

```text
SANIT_TESSERACT_BINARY=/usr/bin/tesseract
SANIT_TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata
```

When `SANIT_REQUIRE_OCR=1`, the preflight verifier refuses production startup if Tesseract is unavailable.

### Installing Tesseract

On a connected staging host using approved Ubuntu repositories:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr
```

For an air-gapped SOC environment, install Tesseract and its required language data from your approved internal/offline package source. Do not depend on public package repositories from the production host.

Confirm:

```bash
tesseract --version
```

The default OCR language is English (`eng`). Additional language packs can be installed locally and selected through `SANIT_OCR_LANG` when required.

## OCR limitations

OCR accuracy depends on source quality. Very low-resolution screenshots, handwriting, severe rotation, stylized fonts, poor contrast or intentionally obfuscated text can reduce recognition accuracy. For highly sensitive evidence, include a visual review of sanitized images/scans in the acceptance process.

Multi-page TIFF is supported. Animated/multi-frame non-TIFF images fail closed. Unsupported DOCX embedded image formats fail closed. Password-protected PDFs and PDFs containing embedded files remain unsupported.

## Bootstrap accounts

Create the first administrator interactively:

```bash
.venv/bin/python main.py --create-user socadmin --role admin
```

Create an analyst:

```bash
.venv/bin/python main.py --create-user analyst01 --role analyst
```

Account maintenance:

```bash
.venv/bin/python main.py --list-users
.venv/bin/python main.py --reset-password analyst01
.venv/bin/python main.py --disable-user analyst01
.venv/bin/python main.py --enable-user analyst01
```

Passwords are entered interactively and are not stored in plaintext.

## Security controls

- Werkzeug scrypt password hashing
- Analyst/Admin server-side authorization
- CSRF protection on uploads, logout and rule changes
- `Secure`, `HttpOnly`, `SameSite=Strict` cookies
- Stable persistent session signing key
- CSP, frame-deny, no-sniff, referrer and permissions headers
- Authenticated download links with job tokens
- Minimal public `/healthz`; detailed `/health` requires authentication
- Gunicorn/systemd production service
- Archive path/symlink/size/count/depth controls
- Local-only OCR processing
- Fail-closed handling for unsupported document/image content

## Pre-deployment verification

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
SANIT_REQUIRE_OCR=1 python scripts/verify_environment.py
```

Expected:

```text
OCR:       OK (tesseract ...)
RESULT: PASSED
```

The production environment also sets `SANIT_REQUIRE_ADMIN=1`, so the verifier will refuse startup until an enabled Administrator exists.

## Functional test suite

```bash
pip install -r requirements-ci.txt
python -m pytest -q tests
```

Tests cover authentication/RBAC/CSRF, output modes, encoding preservation, archive safety, PDF/DOCX, standalone image OCR, scanned PDF OCR and DOCX embedded-image OCR.

## Building the air-gapped Python bundle

On an approved builder with the same target OS/CPU architecture:

```bash
bash scripts/build_offline_bundle.sh
```

Output:

```text
dist/SanitizationApp-v2.1-offline-<arch>.tar.gz
dist/SanitizationApp-v2.1-offline-<arch>.tar.gz.sha256
```

The bundle contains the Python wheelhouse and application code. It uses `--no-index --find-links=./wheels` during installation.

**Important:** Tesseract is a native/OS dependency and is not automatically downloaded by the application or Python wheel bundle. Install it separately from an approved offline/internal source on the target host, or provide an approved local Tesseract executable.

If `.7z`/`.rar` support is required, you may also provide an approved portable 7-Zip binary during bundle build:

```bash
SANIT_7ZIP_BINARY=/approved/path/7zz bash scripts/build_offline_bundle.sh
```

## Offline Python installation

```bash
tar -xzf SanitizationApp-v2.1-offline-<arch>.tar.gz
cd SanitizationApp-v2.1-offline-<arch>
bash scripts/install_offline.sh
```

Then verify native OCR separately:

```bash
tesseract --version
SANIT_REQUIRE_OCR=1 .venv/bin/python scripts/verify_environment.py
```

## Gunicorn production model

Default:

```text
Bind:             0.0.0.0:8443
Worker class:     gthread
Gunicorn workers: 1
HTTP threads:     4
Timeout:          120 seconds
Graceful timeout: 30 seconds
TLS:              enabled
```

v2.1 intentionally enforces:

```text
SANIT_GUNICORN_WORKERS=1
```

Sanitization jobs currently execute in background threads and live progress is process-local. Do not increase worker count until jobs move to an external queue/worker service.

Validate:

```bash
.venv/bin/gunicorn --check-config --config gunicorn.conf.py wsgi:application
```

## systemd installation on Ubuntu

Expected paths:

```text
Application:   /opt/sanitization-app
Service user:  sanitizer
Configuration: /etc/sanitization-app/sanitization.env
```

Create service account:

```bash
sudo useradd --system --home /opt/sanitization-app --shell /usr/sbin/nologin sanitizer 2>/dev/null || true
```

Place application and create runtime directories:

```bash
sudo mkdir -p /opt/sanitization-app
sudo cp -a . /opt/sanitization-app/
sudo mkdir -p /opt/sanitization-app/{uploads,outputs,logs,temp,data,certs}
sudo chown -R sanitizer:sanitizer /opt/sanitization-app/uploads \
  /opt/sanitization-app/outputs \
  /opt/sanitization-app/logs \
  /opt/sanitization-app/temp \
  /opt/sanitization-app/data \
  /opt/sanitization-app/certs
```

Create Administrator as service identity:

```bash
cd /opt/sanitization-app
sudo -u sanitizer .venv/bin/python main.py --create-user socadmin --role admin
```

Install environment configuration:

```bash
sudo mkdir -p /etc/sanitization-app
sudo cp /opt/sanitization-app/deploy/sanitization.env.example /etc/sanitization-app/sanitization.env
sudo chown root:sanitizer /etc/sanitization-app/sanitization.env
sudo chmod 640 /etc/sanitization-app/sanitization.env
```

Verify the `sanitizer` identity can execute Tesseract:

```bash
sudo -u sanitizer tesseract --version
```

Install and enable service:

```bash
sudo cp /opt/sanitization-app/deploy/sanitization-app.service /etc/systemd/system/sanitization-app.service
sudo systemctl daemon-reload
sudo systemctl enable --now sanitization-app
```

Validate:

```bash
sudo systemctl status sanitization-app --no-pager
curl -k https://127.0.0.1:8443/healthz
sudo journalctl -u sanitization-app -n 200 --no-pager
```

Expected health response:

```json
{"status":"ok"}
```

## TLS certificate

The self-signed certificate is for staging. Production should use an approved internal CA certificate:

```text
SANIT_TLS_CERT=/path/to/approved/server.crt
SANIT_TLS_KEY=/path/to/approved/server.key
```

The service identity must be able to read the key, but it must not be world-readable.

## Network restriction

Expose TCP/8443 only to approved SOC/admin networks. Do not expose the application directly to the public internet.

## Staging acceptance checklist

Before production promotion, verify:

1. Authentication, Analyst/Admin RBAC and logout work as intended.
2. Direct single-file jobs return `*_SANITIZED.<ext>` plus a separate Excel report.
3. Folder/multi-file jobs return a ZIP and preserve nested paths.
4. UTF-8/UTF-16/Windows-1252 text files sanitize without encoding corruption.
5. XLS/XLSX sanitization works.
6. Text-based PDF redaction removes configured test matches and the PDF reopens.
7. A scanned/image PDF containing a configured test keyword is OCR-detected and permanently masked.
8. PNG and JPG screenshots containing configured test keywords are OCR-detected and permanently masked.
9. Multi-page TIFF is tested if used operationally.
10. DOCX text, tables, headers/footers and metadata sanitize correctly.
11. Text inside a supported DOCX embedded image is OCR-detected and masked.
12. Re-open sanitized PDF, DOCX and image outputs and visually verify redactions.
13. Excel Audit contains `File Name`, `Match Type`, `Occurrences`, `Location`, `Keywords`.
14. OCR findings have useful locations such as `Image OCR`, `Page N image N OCR` or `DOCX image ... OCR`.
15. Excel `Keywords` shows configured rule text and does not reconstruct arbitrary original source matches.
16. ZIP processing works; 7Z/RAR works when approved 7-Zip is present.
17. Unsupported/corrupt content becomes `Failed` instead of silently passing through.
18. Job History survives application restart and records job creator.
19. `/healthz` returns `status: ok`.
20. `SANIT_REQUIRE_OCR=1 python scripts/verify_environment.py` reports OCR ready.
21. Service survives `systemctl restart` and a test reboot.
22. Approved TLS certificate is presented and TCP/8443 is restricted appropriately.

## Remaining enterprise enhancements

Potential future enhancements include AD/LDAP/SSO, login rate limiting/lockout, richer administrative audit events, dedicated job workers/queue for horizontal scaling, and additional binary format parsers such as PowerPoint/EVTX/PCAP where a defensible sanitization model is defined.
