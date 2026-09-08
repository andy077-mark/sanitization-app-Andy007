# SOC Data Sanitization Platform v2.1

An offline-first SOC utility for sanitizing sensitive information before logs, spreadsheets, documents, screenshots, evidence files or archives are shared. Matched content is replaced or permanently covered with `X` masking while the application produces a sanitized output and a separate Excel audit report.

## v2.1 Highlights

- Modern SOC dashboard and sanitization workspace
- Local sign-in with **Analyst** and **Administrator** roles
- Server-side RBAC for Rules Library administration
- CSRF protection, secure sessions and security headers
- File and **folder** upload from the browser
- Direct sanitized download for a single file selected directly
- ZIP package for folder and multi-file batch jobs with nested paths preserved
- Persistent server-side job history using SQLite (`data/jobs.db`)
- Encoding-aware text sanitization for UTF-8, UTF-8 BOM, UTF-16 LE/BE and Windows-1252
- Dedicated **PDF** and **DOCX** sanitizers
- **Offline OCR** for images, scanned/raster PDF content and DOCX embedded images
- Separate Excel audit report for every successful job
- Excel Audit sheet shows configured **Keywords** / rule text that triggered matches
- Archive traversal/symlink/size/count/depth protections
- No cloud OCR and no runtime dependency downloads
- Gunicorn + hardened Ubuntu systemd production configuration
- Automated Ubuntu 22.04 / 24.04 compatibility validation

## Roles

### Analyst

- Sign in/out
- Sanitize files, folders, documents, images and archives
- Monitor jobs and view history
- Download sanitized outputs and Excel audit reports
- View active-rule count

### Administrator

Includes all Analyst permissions plus full Rules Library administration.

## Requirements

- Python 3.10+
- Packages from `requirements.txt`
- **Tesseract OCR installed locally** for images and scanned-document OCR
- Optional local/bundled 7-Zip for `.7z`, `.rar` and specialist archive formats

The browser interface has no CDN, external fonts, analytics or third-party JavaScript dependency. OCR is performed locally; the app does not send images or document content to a cloud OCR service.

## First-time setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --create-user socadmin --role admin
```

For OCR on Ubuntu, install an organization-approved local Tesseract package. On a normal connected staging host this is typically:

```bash
sudo apt-get install tesseract-ocr
```

For an air-gapped SOC server, install Tesseract from your approved internal/offline package source instead. You can also point the app to an approved local executable:

```text
SANIT_TESSERACT_BINARY=/path/to/tesseract
SANIT_TESSDATA_DIR=/path/to/tessdata
```

Create an analyst account:

```bash
.venv/bin/python main.py --create-user analyst01 --role analyst
```

Passwords are entered interactively and are not placed on the command line.

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
- UTF-16 Little Endian, including conservative BOM-less detection
- UTF-16 Big Endian, including conservative BOM-less detection
- Windows-1252 legacy text

The detected encoding/BOM is preserved so UTF-16 and legacy exports do not become garbled after sanitization.

### Spreadsheets

- `.xlsx`
- `.xls`

### Images + OCR

Standalone raster images are OCR-scanned locally and sensitive text matching the active Rules Library is permanently overwritten in the image pixels.

Supported image formats:

```text
.png .jpg .jpeg .bmp .tif .tiff .webp
```

Multi-page TIFF is supported. Source image metadata such as EXIF/text metadata is not copied into the sanitized output. Animated/multi-frame non-TIFF images fail closed rather than being partially sanitized.

Example:

```text
Input:  screenshot.png containing User=andy
Output: screenshot_SANITIZED.png with the detected text area permanently masked
Audit:  Image OCR | configured keyword/rule
```

### PDF

PDF sanitization covers both normal extractable text and raster/scanned content:

- extractable PDF text is removed using permanent PDF redaction,
- raster image regions are rendered locally and inspected with Tesseract OCR,
- OCR matches are mapped back to page coordinates and permanently redacted,
- PDF metadata is sanitized,
- Excel audit locations include `Page 3` or `Page 3 image 1 OCR`.

Password-protected PDFs and PDFs containing embedded files still fail closed.

### Word DOCX

`.docx` is sanitized as a structured Office document. Coverage includes:

- paragraphs and text split across Word runs,
- tables,
- headers and footers,
- footnotes, endnotes and comments where present,
- document metadata,
- external relationship targets such as hyperlinks,
- drawing/image alt text,
- supported raster images under `word/media/` using local OCR.

Embedded/OLE files and macro payloads fail closed. Unsupported embedded image types also fail closed instead of being silently passed through.

### Archives and compression

- Native: `.zip`, `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.gz`, `.bz2`, `.xz`
- With local 7-Zip: `.7z`, `.rar`, `.lz`, `.zst` and supported specialist formats

Nested archives are processed up to the configured depth limit. Supported PDFs, DOCX files and images found inside an extracted archive are passed through their dedicated sanitizers.

### Other binary formats

Old `.doc`, PowerPoint, GIF, EVTX, PCAP, executables, databases and other unsupported binary formats are not treated as plain text. Unsupported content fails clearly rather than being returned unchanged and mistaken for sanitized output.

## OCR configuration

Production defaults are documented in `deploy/sanitization.env.example`:

```text
SANIT_REQUIRE_OCR=1
SANIT_OCR_LANG=eng
SANIT_OCR_DPI=200
SANIT_OCR_PSM=6
SANIT_OCR_MIN_CONFIDENCE=0
SANIT_OCR_TIMEOUT_SECONDS=120
SANIT_MAX_IMAGE_PIXELS=120000000
```

`SANIT_REQUIRE_OCR=1` makes the production environment preflight fail if a local Tesseract engine cannot be found.

OCR is a detection technology and is not mathematically perfect. Very low-resolution screenshots, handwriting, extreme rotations, stylized/obfuscated text or poor scans can reduce recognition accuracy. High-risk evidence should still receive a visual review after sanitization.

## Output behavior

### Single file selected directly

A single file selected with **Browse Files** is returned directly rather than unnecessarily wrapped in a ZIP.

```text
Input:
incident.pdf

Outputs:
incident_SANITIZED.pdf
Sanitization_Report_<job_id>.xlsx
```

The same behavior applies to DOCX, supported images, text files, spreadsheets and directly selected supported archives.

### Folder or multi-file batch

A folder upload or job containing multiple files is returned as one ZIP package so relative folder structure is retained.

```text
Sanitized_Package_<job_id>.zip
├── Sanitized_Files/
│   └── Case-01/
│       ├── screenshot_SANITIZED.png
│       ├── incident.docx
│       ├── report.pdf
│       └── Logs/
│           └── security.log
└── Sanitization_Report_<job_id>.xlsx
```

The Excel report is also available as a separate download. A Browse Folder job remains a folder/batch job even when it contains only one file.

## Excel audit report

Every successful job creates:

```text
Sanitization_Report_<job_id>.xlsx
```

The workbook contains **Summary** and **Audit** sheets. Audit columns are:

- **File Name**
- **Match Type**
- **Occurrences**
- **Location** — line, spreadsheet cell, PDF page/OCR image, DOCX paragraph/image, filename or path where available
- **Keywords** — configured Rules Library keyword/regular expression that produced the match

Example:

| File Name | Match Type | Occurrences | Location | Keywords |
|---|---|---:|---|---|
| incident.pdf | Custom Rule 1 | 2 | Page 2 image 1 OCR | `andy` |
| screenshot.png | IPv4 Address | 1 | Image OCR | `\b(?:\d{1,3}\.){3}\d{1,3}\b` |

The **Keywords** value is intentionally not sanitized. It shows the configured rule exactly as entered by the Administrator. The report does not reconstruct the original matched source value.

## Rules Library

Rules are regular expressions stored in `bad_words.txt`. Only Administrators can view or modify rule content from the web interface. Analysts can see the active-rule count but cannot access Rules Library endpoints.

## Job history and retention

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

## Testing and production

Testing server:

```bash
.venv/bin/python main.py --serve
```

Production uses `gunicorn.conf.py` and `deploy/sanitization-app.service`. Full production steps are in `DEPLOYMENT.md`.

v2.1 intentionally uses one Gunicorn worker process because live background-job progress is process-local:

```text
SANIT_GUNICORN_WORKERS=1
SANIT_GUNICORN_THREADS=4
```

Do not increase the worker count until job execution is moved to an external worker queue.

## Air-gapped bundle

Build the Python dependency bundle on an approved builder for the target OS/CPU:

```bash
bash scripts/build_offline_bundle.sh
```

The Python package installation uses a local wheelhouse with `--no-index`. **Tesseract is an OS/native OCR dependency and is not downloaded at runtime by the application.** The target SOC host must have Tesseract installed from an approved offline/internal source, or expose an approved local executable through `SANIT_TESSERACT_BINARY`.

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
- PDF native-text redaction
- scanned/raster PDF OCR redaction
- standalone image OCR sanitization and metadata removal
- DOCX structured text and embedded-image OCR sanitization
- fail-closed unsupported/embedded content handling
- Excel Audit report with configured **Keywords**
- malicious archive rejection
- benchmark/Gunicorn validation
- offline Python wheelhouse installation

## Security notes

- Restrict network access to approved SOC/admin networks.
- Use an internal CA certificate in production.
- Keep `SANIT_GUNICORN_WORKERS=1` for v2.1.
- Keep runtime directories writable only by the service identity.
- Use systemd/Gunicorn for production, not Flask's development server.
- Keep Tesseract and language data locally managed/approved; no cloud OCR is required.
- Visually review poor-quality OCR sources when the information is high sensitivity.
- The configured rule is intentionally visible in the Excel report; original matched values are not reconstructed for reporting.
- AD/LDAP/SSO can be added later while retaining the Analyst/Admin authorization model.

## Support

Developed and maintained by Andy.
