# SOC Data Sanitization Platform v2.1

An offline-first SOC utility for sanitizing sensitive information before logs, spreadsheets, documents, evidence files or archives are shared. Matched content is replaced with `X` characters while the application produces a sanitized output and a separate Excel audit report.

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
- Encoding-aware text sanitization for UTF-8, UTF-8 BOM, UTF-16 LE/BE and Windows-1252
- Dedicated **PDF** and **DOCX** sanitizers
- Fail-closed handling for unsupported/unsafe document content instead of silently passing it through
- Separate Excel audit report for every successful job
- Excel Audit sheet shows the configured **Keywords** / rule text that triggered the match
- Archive traversal/symlink/size/count/depth protections
- No runtime dependency downloads
- Pinned runtime dependencies for repeatable offline installs
- **Gunicorn** production WSGI configuration
- Hardened Ubuntu **systemd** service with automatic restart and boot startup
- Automated Ubuntu 22.04 / 24.04 compatibility validation

## Roles

### Analyst

- Sign in/out
- Sanitize files, folders, documents and archives
- Monitor jobs
- View history
- Download sanitized outputs and Excel audit reports
- View active rule count

### Administrator

Includes all Analyst permissions plus full Rules Library administration.

## Requirements

- Python 3.10+
- Packages from `requirements.txt`
- Optional local/bundled 7-Zip for `.7z`, `.rar` and specialist archive formats

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

Full production steps, account bootstrap, automatic restart/startup, TLS and staging acceptance checks are in `DEPLOYMENT.md`.

## Gunicorn worker model

v2.1 intentionally uses one Gunicorn worker process with configurable HTTP threads because sanitization jobs execute in background threads and live progress is held in process memory.

```text
SANIT_GUNICORN_WORKERS=1
SANIT_GUNICORN_THREADS=4
```

Do not increase the worker count above 1 until job execution is moved to an external worker queue.

## Supported content

### Text and SOC/config formats

```text
.txt .log .csv .tsv .json .jsonl .ndjson
.xml .yaml .yml .ini .cfg .conf .config .properties .env
.md .rst .html .htm .css .js .ts .py
.ps1 .psm1 .psd1 .sh .bash .zsh .bat .cmd .vbs
.sql .reg .inf .service .socket .timer .rules .list .hosts
```

Readable text with another extension can also be processed when the application can safely identify its encoding.

Supported text encodings:

- UTF-8
- UTF-8 with BOM
- UTF-16 Little Endian (BOM and conservative BOM-less detection)
- UTF-16 Big Endian (BOM and conservative BOM-less detection)
- Windows-1252 legacy text

The original detected encoding/BOM is preserved so UTF-16 or legacy exports do not become garbled after sanitization.

### Spreadsheets

- `.xlsx`
- `.xls`

### PDF

Text-based `.pdf` files are sanitized using permanent PDF redaction. Matched extractable text is removed and replaced visually with `X` characters. PDF metadata is also sanitized, and the Excel report records locations such as `Page 3` or `PDF metadata: title`.

For safety, the PDF sanitizer fails closed when:

- the PDF is password-protected,
- the PDF contains embedded files,
- a page appears image-only/scanned and therefore requires OCR,
- or a match cannot be mapped safely to page coordinates.

PDF images are not OCR-processed in v2.1. If sensitive text exists only inside an image, OCR support is required before the platform can guarantee sanitization of that image content.

### Word DOCX

`.docx` is sanitized as a structured Office document instead of as plain text. The sanitizer covers:

- document paragraphs and text split across multiple Word runs,
- tables,
- headers and footers,
- footnotes, endnotes and comments where present,
- document metadata,
- external relationship targets such as hyperlinks.

Run/text lengths are preserved so normal formatting structure is retained as much as possible.

For safety, DOCX files containing embedded/OLE files or macro payloads fail closed. Image-only DOCX files require OCR. Text drawn inside images is not OCR-processed in v2.1.

### Archives and compression

- Native: `.zip`, `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.gz`, `.bz2`, `.xz`
- With local 7-Zip: `.7z`, `.rar`, `.lz`, `.zst` and supported specialist formats

Nested archives are processed up to the configured depth limit. Supported PDFs and DOCX files inside extracted archives are sanitized through the same format-specific handlers.

### Other binary formats

Formats such as old `.doc`, PowerPoint, images, EVTX, PCAP, executables and databases are not treated as plain text. Unsupported content fails clearly rather than being returned unchanged and mistaken for a sanitized result.

## Output behavior

### Single file selected directly

A single file selected with **Browse Files** is returned directly rather than wrapped in a ZIP.

```text
Input:
incident.pdf

Outputs:
incident_SANITIZED.pdf
Sanitization_Report_<job_id>.xlsx
```

The same rule applies to `.docx`, text files, spreadsheets and directly selected supported archives.

### Folder or multi-file batch

A folder upload or job containing multiple files is returned as one ZIP package so the original relative folder structure is preserved.

```text
Sanitized_Package_<job_id>.zip
├── Sanitized_Files/
│   └── Case-01/
│       ├── incident.docx
│       ├── report.pdf
│       └── Logs/
│           └── security.log
└── Sanitization_Report_<job_id>.xlsx
```

The Excel report is also available as a separate download.

A **Browse Folder** job remains a folder/batch job even when the selected folder contains only one file. Completely empty folders cannot be preserved by normal browser folder upload because browsers provide files and relative paths rather than standalone empty-directory objects.

## Excel audit report

Every successful job creates:

```text
Sanitization_Report_<job_id>.xlsx
```

The workbook contains **Summary** and **Audit** sheets.

Audit columns:

- **File Name**
- **Match Type**
- **Occurrences**
- **Location** — line, spreadsheet cell, PDF page, DOCX paragraph/metadata, filename or path where available
- **Keywords** — configured Rules Library keyword/regular expression that produced the match

Example:

| File Name | Match Type | Occurrences | Location | Keywords |
|---|---|---:|---|---|
| incident.pdf | Custom Rule 1 | 2 | Page 2 | `andy` |
| evidence.docx | IPv4 Address | 4 | Document paragraph 7 | `\b(?:\d{1,3}\.){3}\d{1,3}\b` |

The **Keywords** value is intentionally not sanitized. It shows the configured rule exactly as entered by the Administrator. The report does not reconstruct the original matched source value; the sanitized output itself replaces matched source content with `X` characters.

## Rules Library

Rules are regular expressions stored in `bad_words.txt`.

Only Administrators can view or modify rule content from the web interface. Analysts can see the active-rule count but cannot access Rules Library endpoints.

## Job history

Persistent metadata is stored in `data/jobs.db`.

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

```text
GET /healthz   # minimal unauthenticated probe
GET /health    # authenticated application health
```

## Air-gapped bundle

Build on an approved internet-connected builder for the target OS/CPU:

```bash
bash scripts/build_offline_bundle.sh
```

The generated bundle contains the local wheelhouse, PDF/DOCX dependencies, application, authentication code, Gunicorn configuration, systemd deployment files, staging acceptance checker, performance benchmark tool and verification scripts.

Install with:

```bash
bash scripts/install_offline.sh
```

Installation uses `--no-index --find-links=./wheels` and does not contact PyPI.

## Performance benchmark

Run synthetic real-server benchmarks with the server's active Rules Library:

```bash
.venv/bin/python scripts/benchmark_performance.py --sizes-mb 100 500 1024 2048
```

See `PERFORMANCE_BENCHMARK.md` for methodology and result interpretation.

## Automated validation

The compatibility workflow validates:

- Ubuntu 22.04 / Python 3.10
- Ubuntu 24.04 / Python 3.12
- authentication, RBAC, CSRF and security headers
- direct single-file and folder/multi-file output modes
- nested folder-path preservation
- UTF-8/UTF-16/Windows-1252 handling
- PDF text redaction and PDF reopen validation
- image-only PDF fail-closed behavior
- DOCX cross-run text, tables, headers and metadata sanitization
- DOCX embedded-content fail-closed behavior
- unsupported binary fail-closed handling
- Excel Audit report with configured **Keywords**
- persistent job history
- malicious archive path rejection
- performance benchmark smoke test
- Gunicorn configuration
- offline wheelhouse installation

## Security notes

- Restrict network access to approved SOC/admin networks.
- Use an internal CA certificate in production.
- Keep `SANIT_GUNICORN_WORKERS=1` for v2.1.
- Keep runtime directories writable only by the service identity.
- Use systemd/Gunicorn for production, not Flask's development server.
- PDF/DOCX image text is not OCR-sanitized in v2.1; image-only content fails closed where detected.
- The configured rule is intentionally visible in the Excel report; the original matched source value is not reconstructed for reporting.
- AD/LDAP/SSO can be added later while retaining the Analyst/Admin authorization model.

## Support

Developed and maintained by Andy.
