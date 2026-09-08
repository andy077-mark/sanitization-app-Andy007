# SOC Data Sanitization Platform v2.0

An offline-first SOC utility for sanitizing sensitive information before logs, spreadsheets, evidence files or archives are shared. Matched content is replaced with `X` characters while the application produces a sanitized output package and a safe Excel audit report.

## v2.0 Highlights

- Modern SOC dashboard and sanitization workspace
- File and **folder** upload from the browser
- One auditable job can contain multiple files
- Persistent server-side job history using SQLite (`data/jobs.db`)
- Reliable `Queued`, `Processing`, `Done` and `Failed` job states
- Interrupted jobs are marked failed after an application restart instead of remaining stuck
- Sanitized output packaged as `Sanitized_Package_<job_id>.zip`
- Excel evidence report: `Sanitization_Report_<job_id>.xlsx`
- Audit report includes:
  - File Name
  - Match Type
  - Occurrences
  - Location (line/cell/filename where available)
  - Safe Example (after sanitization)
- ZIP/TAR/GZ/BZ2/XZ processing using the Python standard library
- RAR/7Z and other specialist archive formats use a **locally installed or bundled 7-Zip** binary
- Archive safety controls for traversal, symlinks, extraction size, file count and nesting depth
- No runtime download of 7-Zip from the application
- Flask debug mode disabled in server mode
- Rule management remains available from the browser

## Supported Content

- Text/log data: `.txt`, `.log`, `.csv` and UTF-8 readable text files
- Spreadsheets: `.xlsx`, `.xls`
- Archives/compression: `.zip`, `.tar`, `.tgz`, `.tar.gz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.gz`, `.bz2`, `.xz`
- With local 7-Zip: `.7z`, `.rar`, `.lz`, `.zst` and other formats supported by that binary

Nested archives are processed up to the configured depth limit.

## Requirements

- Python 3.10+
- Packages from `requirements.txt`
- Optional local/bundled 7-Zip for RAR/7Z and specialist archive formats

> The web interface has no CDN, external font, analytics or external JavaScript dependency. Python packages and optional 7-Zip still need to be installed or provided locally before first use in a fully air-gapped environment.

## Quick Start

### Linux / Ubuntu / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py --serve
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py --serve
```

Then open:

```text
https://localhost:8443
```

A browser warning is expected when using the application's local self-signed certificate.

## Workflow

1. Open **New Sanitization**.
2. Choose **Browse Files** or **Browse Folder**.
3. Review the selected files.
4. Click **Start Sanitization**.
5. Monitor the job status and progress.
6. When complete, download:
   - **Sanitized Package**
   - **Excel Audit Report**
7. Previous jobs remain visible in **Job History** even after a browser restart.

## Rules Library

Rules are regular expressions stored in `bad_words.txt`.

The UI supports:

- Add rule
- Edit rule
- Delete rule
- Save all rules
- Clear all rules
- Replace rules from a UTF-8 `.txt` file

Lines beginning with `#` are comments and are ignored.

### Examples

| Pattern | Example |
|---|---|
| `2023` | `10-02-2023` → `10-02-XXXX` |
| `\bandy\b` | `Andy` → `XXXX` |
| `\b[\w\.-]+@company\.com\b` | company email addresses are redacted |

## Job History

Job metadata is stored in:

```text
data/jobs.db
```

Default retention:

- Sanitized packages/reports: **1 day**
- Job history metadata: **90 days**

These values can be changed using environment variables:

```text
SANIT_OUTPUT_RETENTION_DAYS
SANIT_HISTORY_RETENTION_DAYS
```

## Archive Safety Limits

Defaults:

```text
Maximum extracted size: 4096 MB
Maximum extracted files: 10000
Maximum nested archive depth: 5
7-Zip processing timeout: 300 seconds
```

Configure with:

```text
SANIT_MAX_EXTRACTED_MB
SANIT_MAX_EXTRACTED_FILES
SANIT_MAX_ARCHIVE_DEPTH
SANIT_ARCHIVE_TIMEOUT_SECONDS
```

## Folder Structure

```text
SanitizationApp/
├── main.py                  # compatibility entry point
├── sanitization_v2/        # modular v2 backend
│   ├── app.py
│   ├── config.py
│   ├── jobs.py
│   ├── rules.py
│   └── sanitize.py
├── bad_words.txt
├── requirements.txt
├── start.sh
├── start.bat
├── templates/
│   └── index.html
├── data/
│   └── jobs.db              # created automatically
├── uploads/                 # temporary
├── outputs/                 # packages and Excel reports
├── logs/
├── temp/
├── tools/
│   └── 7zip/                # optional bundled 7-Zip
└── certs/                    # generated local certificate
```

## Health Endpoint

```text
GET /health
```

Returns application status, version, local/offline mode, upload limits and whether 7-Zip is available.

## CLI

```bash
python main.py test.txt
python main.py test.txt --rules-file bad_words.txt
python main.py test.txt --rules "secret" "2026"
```

The CLI now produces the same ZIP package and Excel audit report used by the web application.

## Security Notes

- Deploy inside a trusted network unless authentication and authorization are added.
- The current self-signed certificate is suitable for internal testing; enterprise deployments should use an approved internal certificate.
- Rules management changes sanitization behavior and should be restricted to authorized administrators in a future authentication release.
- Test upgrades in a staging environment before replacing a working SOC deployment.

## Support

Developed and maintained by Andy.
