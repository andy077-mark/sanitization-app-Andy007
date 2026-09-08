# SOC Data Sanitization Platform v2.1

An offline-first SOC utility for sanitizing sensitive information before logs, spreadsheets, evidence files or archives are shared. Matched content is replaced with `X` characters while the application produces a sanitized output and a separate Excel audit report.

## v2.1 Highlights

- Modern SOC dashboard and sanitization workspace
- Local sign-in with **Analyst** and **Administrator** roles
- Server-side RBAC for Rules Library administration
- CSRF protection for uploads, logout and rule changes
- Secure session cookies and stable session signing key
- File and **folder** upload from the browser
- One auditable job can contain multiple files
- Persistent server-side job history using SQLite (`data/jobs.db`)
- Job creator recorded in persistent history
- Reliable `Queued`, `Processing`, `Done` and `Failed` states
- Direct sanitized download for a single file selected directly
- ZIP package for folder and multi-file batch jobs
- Nested folder structure preserved inside batch packages
- Encoding-aware text sanitization with UTF-8, UTF-8 BOM, UTF-16 LE/BE and Windows-1252 support
- Fail-closed handling for unsupported binary/document formats instead of silently passing them through
- Separate Excel audit report for every successful job
- Excel Audit sheet shows the configured **Keywords** / rule text that triggered the match
- Archive traversal/symlink/size/count/depth protections
- No runtime dependency or 7-Zip downloads
- Pinned runtime dependencies for repeatable offline installs
- **Gunicorn** production WSGI configuration
- Hardened Ubuntu **systemd** service with automatic restart and boot startup
- Automated Ubuntu 22.04 / 24.04 compatibility validation

## Roles

### Analyst

- Sign in/out
- Sanitize files/folders/archives
- Monitor jobs
- View history
- Download sanitized outputs and Excel audit reports
- View active rule count

### Administrator

Includes all Analyst permissions plus full Rules Library administration.

## Requirements

- Python 3.10+
- Packages from `requirements.txt`
- Optional local/bundled 7-Zip for `.7z`, `.rar` and specialist formats

The browser interface has no CDN, external fonts, analytics or third-party JavaScript dependency.

## First-time setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --create-user socadmin --role admin
```

Create an analyst account:

```bash
.venv/bin/python main.py --create-user analyst01 --role analyst
```

Passwords are entered interactively and are not placed on the command line.

## Testing server

```bash
.venv/bin/python main.py --serve
```

Open:

```text
https://localhost:8443
```

The local self-signed certificate is intended for staging/testing. Production should use an approved internal CA certificate.

## Production server

Gunicorn configuration:

```text
gunicorn.conf.py
```

Manual production launch:

```bash
bash scripts/start_production.sh
```

Ubuntu systemd unit:

```text
deploy/sanitization-app.service
```

Full production steps, account bootstrap, automatic restart/startup, TLS and staging acceptance checks are in:

```text
DEPLOYMENT.md
```

## Gunicorn worker model

v2.1 intentionally uses one Gunicorn worker process with configurable HTTP threads because sanitization jobs execute in background threads and live progress is held in process memory.

Default:

```text
SANIT_GUNICORN_WORKERS=1
SANIT_GUNICORN_THREADS=4
```

The configuration refuses a worker count above 1 until job execution is moved to an external worker queue.

## Supported content

### Text and SOC/config formats

The normal line-oriented sanitizer now supports these text-based extensions directly:

```text
.txt .log .csv .tsv .json .jsonl .ndjson
.xml .yaml .yml .ini .cfg .conf .config .properties .env
.md .rst .html .htm .css .js .ts .py
.ps1 .psm1 .psd1 .sh .bash .zsh .bat .cmd .vbs
.sql .reg .inf .service .socket .timer .rules .list .hosts
```

Readable text with another extension can also be processed when the application can safely identify its encoding.

Supported text encodings include:

- UTF-8
- UTF-8 with BOM
- UTF-16 Little Endian, with BOM and conservative BOM-less detection
- UTF-16 Big Endian, with BOM and conservative BOM-less detection
- Windows-1252 legacy text

The sanitizer preserves the detected encoding/BOM instead of rewriting every text file as UTF-8. This prevents UTF-16/legacy exports from becoming garbled or displaying Chinese-looking characters after sanitization.

### Spreadsheets

- `.xlsx`
- `.xls`

### Archives and compression

- Native: `.zip`, `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.gz`, `.bz2`, `.xz`
- With local 7-Zip: `.7z`, `.rar`, `.lz`, `.zst` and supported specialist formats

Nested archives are processed up to the configured depth limit.

### Not yet supported as document formats

Binary/document formats such as PDF, Word, PowerPoint, images, EVTX and PCAP are not treated as plain text. The job fails clearly rather than returning an unchanged file that could be mistaken for a sanitized result. Dedicated parsers can be added for these formats in a future release.

## Output behavior

The application chooses the output mode based on how the user selected the data.

### Single file selected directly

A single file selected with **Browse Files** is returned directly. It is not unnecessarily wrapped in a ZIP.

Example:

```text
Input:
security.log

Outputs:
security_SANITIZED.log
Sanitization_Report_<job_id>.xlsx
```

The direct output keeps the original file type where supported. A directly selected archive is returned as the sanitized/repacked archive with `_SANITIZED` added to the filename.

### Folder or multi-file batch

A folder upload or a job containing multiple files is returned as one ZIP package so the original relative folder structure can be preserved.

Example input:

```text
Case-01/
├── notes.txt
└── Logs/
    ├── firewall.log
    └── Windows/
        └── Security/
            └── security.log
```

Example output:

```text
Sanitized_Package_<job_id>.zip
├── Sanitized_Files/
│   └── Case-01/
│       ├── notes.txt
│       └── Logs/
│           ├── firewall.log
│           └── Windows/
│               └── Security/
│                   └── security.log
└── Sanitization_Report_<job_id>.xlsx
```

The Excel report is also available as a separate download.

If **Browse Folder** is used, the job remains a folder/batch job even when the selected folder happens to contain only one file. This preserves the folder context instead of silently converting the result to a standalone file.

Completely empty folders cannot be preserved by normal browser folder upload because browsers provide files and their relative paths rather than standalone empty-directory objects.

## Excel audit report

Every successful job creates:

```text
Sanitization_Report_<job_id>.xlsx
```

The workbook contains **Summary** and **Audit** sheets.

The Audit sheet contains:

- **File Name**
- **Match Type**
- **Occurrences**
- **Location** — line, cell, filename or path where available
- **Keywords** — the configured Rules Library keyword/regular expression that produced the match

Example:

| File Name | Match Type | Occurrences | Location | Keywords |
|---|---|---:|---|---|
| security.log | Custom Rule 1 | 4 | Line 23 | `andy` |
| security.log | IPv4 Address | 18 | Line 31 | `\b(?:\d{1,3}\.){3}\d{1,3}\b` |

The **Keywords** value is intentionally **not sanitized**. It shows the configured rule exactly as entered by the Administrator so the SOC analyst can identify which rule triggered.

The report does **not** attempt to reconstruct or reproduce the original matched value from the source document. Only the configured rule/keyword is shown. The sanitized output file itself still replaces matched content with `X` characters.

## Rules Library

Rules are regular expressions stored in `bad_words.txt`.

Only Administrators can view or modify rule content from the web interface. Analysts can see the active-rule count but cannot access Rules Library endpoints.

## Job history

Persistent metadata is stored in:

```text
data/jobs.db
```

Default retention:

```text
Sanitized outputs/reports: 1 day
Job history metadata:      90 days
```

Configure with:

```text
SANIT_OUTPUT_RETENTION_DAYS
SANIT_HISTORY_RETENTION_DAYS
```

## User-management CLI

```bash
.venv/bin/python main.py --list-users
.venv/bin/python main.py --reset-password analyst01
.venv/bin/python main.py --disable-user analyst01
.venv/bin/python main.py --enable-user analyst01
```

## Health endpoints

Minimal unauthenticated service probe:

```text
GET /healthz
```

Authenticated application health:

```text
GET /health
```

## Air-gapped bundle

Build on an approved internet-connected builder for the target OS/CPU:

```bash
bash scripts/build_offline_bundle.sh
```

The generated v2.1 bundle contains the local wheelhouse, application, authentication code, Gunicorn configuration, systemd deployment files, staging acceptance checker, performance benchmark tool and verification scripts.

Install on the air-gapped host with:

```bash
bash scripts/install_offline.sh
```

Installation uses `--no-index --find-links=./wheels` and does not contact PyPI.

## Automated validation

The GitHub Actions compatibility workflow tests:

- Ubuntu 22.04 / Python 3.10
- Ubuntu 24.04 / Python 3.12
- Local login/logout
- Analyst/Admin RBAC
- CSRF enforcement
- Security headers
- Direct single-file sanitized output
- Multi-file/folder ZIP output
- Nested folder-path preservation
- UTF-8 BOM preservation
- UTF-16 LE/BE preservation without garbled output
- Windows-1252 processing
- Expanded text extension handling
- Fail-closed rejection of known unsupported binary/document files
- Excel report with unsanitized configured **Keywords**
- Persistent job history
- Malicious archive path rejection
- Performance benchmark smoke test
- Gunicorn configuration
- Offline wheelhouse installation

## Security notes

- Restrict network access to approved SOC/admin networks.
- Use an internal CA certificate in production.
- Keep `SANIT_GUNICORN_WORKERS=1` for v2.1.
- Keep runtime directories writable only by the service identity.
- Use `systemd`/Gunicorn for production, not Flask's development server.
- Do not force unsupported binary/document formats through the text sanitizer; add a dedicated parser instead.
- The configured keyword/rule is intentionally visible in the Excel report; the original matched source value is not reconstructed for the report.
- AD/LDAP/SSO integration can be added later while retaining the Analyst/Admin authorization model.

## Support

Developed and maintained by Andy.
