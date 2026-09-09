# SOC Data Sanitization Platform v2.1

An offline-first SOC utility for sanitizing sensitive information before logs, spreadsheets, documents, evidence files or archives are shared. Matched content is replaced with `X` characters while the application produces a sanitized output and a separate Excel audit report.

## DevOps handoff - read this first

For production or staging deployment, DevOps should use this README together with:

- `DEPLOYMENT.md` - detailed production deployment, service, TLS, logs, staging acceptance and rollback guidance.
- `OS_COMPATIBILITY_REVIEW.md` - Ubuntu 22.04 -> 24.04 incident investigation, dependency-chain review and OS-upgrade procedure.
- `PERFORMANCE_BENCHMARK.md` - real-server performance validation methodology.
- `requirements-lock.txt` - authoritative complete direct + transitive Python runtime dependency lock.
- `RUNTIME_MANIFEST.json` - included in release bundles and used to reject deployment to the wrong Ubuntu/Python/architecture target.

### Critical operational rules

1. **Never reuse the existing `.venv` after an Ubuntu release upgrade.** Deploy the offline bundle built for the new OS/Python/architecture and allow the installer to rebuild `.venv`.
2. **Production/air-gapped installation must use the prepared offline release.** Do not use `--online` in production.
3. **Do not increase Gunicorn beyond one worker in v2.1.** Background job state is process-local. Threads may be used as configured.
4. **Do not treat images or scanned/image-only PDFs as sanitized.** OCR is not included and unsupported content fails closed.
5. **Do not store passwords, private TLS keys, internal credentials or sensitive SOC data in the repository.** User passwords are entered interactively and stored only as password hashes.
6. Restrict TCP/8443 to approved SOC/admin networks and replace the staging self-signed certificate with an approved internal CA certificate for production.
7. After every deployment or OS upgrade, run environment verification, health checks, staging acceptance and at least one representative sanitization job before returning the service to users.

## v2.1 Highlights

- Modern SOC dashboard and sanitization workspace
- Local **Analyst** and **Administrator** roles with server-side RBAC
- Administrator UI for Rules Library, User Management and local Application Logs
- Live Server & Runtime Overview for hostname, Ubuntu/platform, Python, CPU, logical CPUs, memory, disk and disk utilization
- CSRF protection, secure sessions and security headers
- File and folder upload with persistent SQLite job history
- Direct sanitized download for one directly selected file
- ZIP package for folder and multi-file jobs with nested paths preserved
- Encoding-aware text handling for UTF-8, UTF-8 BOM, UTF-16 LE/BE and Windows-1252
- Dedicated text-based **PDF** and structured **DOCX** sanitizers
- XLS/XLSX sanitization
- Fail-closed handling for unsupported/unsafe content
- Separate Excel audit report with `File Name`, `Match Type`, `Occurrences`, `Location`, `Keywords`
- Archive traversal/symlink/size/count/depth protections
- Complete direct + transitive runtime dependency lock
- OS/Python/architecture-specific offline release bundles
- Wheel SHA-256 integrity verification
- Startup preflight to detect a stale bundle after an Ubuntu/Python upgrade
- **No Python package download during offline target installation, startup or runtime**
- Gunicorn + hardened Ubuntu systemd deployment
- Automated compatibility and offline-install testing on Ubuntu 22.04, 24.04 and 26.04 LTS

## Current UI / operational layout

The production interface provides:

- **Dashboard** - job KPIs, quick actions, current job status and live server/runtime information.
- **Sanitize Files** - file/folder selection, drag-and-drop, processing progress and sanitized/report downloads.
- **Reports / History** - persistent job history, search, refresh, JSON export and output/report links.
- **Rules Library (Admin)** - add, edit, delete, bulk-save, clear and replace sanitization rules.
- **User Management (Admin)** - create local Analyst/Admin users, enable/disable accounts and reset passwords.
- **Application Logs (Admin)** - read recent local `processing.log` entries from the browser.
- **About / System** - compatibility and live runtime overview.

The live system values are detected from the host at runtime and are not hardcoded into the UI.

Important UI/runtime files include:

```text
templates/index.html
templates/login.html
sanitization_v2/static/theme.css
sanitization_v2/static/login.css
sanitization_v2/static/dashboard.js
sanitization_v2/ui_extension.py
```

The production environment verifier checks required application/UI assets before startup.

## Supported Ubuntu releases

The release workflow validates each OS with a fresh virtual environment built from that OS's system Python:

| Ubuntu | System Python validated | Status |
|---|---:|---|
| 22.04 LTS | 3.10 | Automated functional + offline-bundle test |
| 24.04 LTS | 3.12 | Automated functional + offline-bundle test |
| 26.04 LTS | 3.14 | Automated functional + offline-bundle test |

**Do not reuse an existing `.venv` across an Ubuntu release upgrade.** Ubuntu releases can use different default Python minor versions, so the application virtual environment must be rebuilt from the release bundle created for the new OS/Python combination.

See `OS_COMPATIBILITY_REVIEW.md` for the full Ubuntu upgrade investigation, dependency chain and future-upgrade procedure.

## Runtime dependencies

`requirements.txt` lists the direct application dependencies. `requirements-lock.txt` is the authoritative release lock and includes every direct and transitive Python runtime dependency at an exact version.

The environment verifier checks the full lock before production startup. A missing or mismatched package causes preflight failure rather than allowing a partially compatible runtime to start.

## Internet / air-gap behavior

### Build environment

An approved connected build/CI machine may download Python wheels while creating the release artifact. This is a release-engineering step only.

### Target installation

The OS-specific offline release contains:

- application source, templates and static UI assets,
- all required Python wheels,
- `requirements-lock.txt`,
- `WHEELS_SHA256SUMS.txt`,
- `RUNTIME_MANIFEST.json`,
- deployment, verification, acceptance and benchmark scripts,
- optional approved 7-Zip binary when supplied during release build.

Offline installation uses:

```text
PIP_NO_INDEX=1
--no-index
--find-links=<local wheels directory>
```

It does not contact PyPI or another Python repository.

### Startup / runtime

The application does not download Python libraries, executables, fonts, JavaScript frameworks, analytics components or sanitization components during startup or runtime. The UI uses local assets only. The 7-Zip helper searches bundled/local/system locations only and never downloads 7-Zip.

The Ubuntu host itself must already provide the matching system `python3` and `python3-venv`. In an air-gapped environment those OS packages must come from approved internal/offline Ubuntu media. `systemd` is used for the production service. 7-Zip is optional and is required only for formats such as `.7z` and `.rar`; ZIP/TAR/GZ/BZ2/XZ use Python's standard library.

## Roles

### Analyst

- Sign in/out
- Sanitize supported files, folders, documents and archives
- Monitor jobs and view history
- Download sanitized outputs and Excel reports
- View active-rule count
- View system/runtime overview

### Administrator

Includes all Analyst capabilities plus:

- Rules Library administration
- Create Analyst/Admin users
- Enable/disable users
- Reset local user passwords
- View recent local application logs

Rules/user/log endpoints are protected server-side; hiding controls in the UI is not the security boundary.

## Supported content

### Text and SOC/config formats

```text
.txt .log .csv .tsv .json .jsonl .ndjson
.xml .yaml .yml .ini .cfg .conf .config .properties .env
.md .rst .html .htm .css .js .ts .py
.ps1 .psm1 .psd1 .sh .bash .zsh .bat .cmd .vbs
.sql .reg .inf .service .socket .timer .rules .list .hosts
```

Other files can also be processed when they are safely detected as supported text.

Supported encodings:

- UTF-8
- UTF-8 BOM
- UTF-16 Little Endian
- UTF-16 Big Endian
- Windows-1252

The detected encoding/BOM is preserved to avoid garbled output.

### Spreadsheets

- `.xlsx`
- `.xls`

### PDF

Text-based PDF files are sanitized using permanent PDF redaction. PDF metadata is also sanitized and the Excel audit can record locations such as `Page 3`.

The PDF sanitizer fails closed for password-protected PDFs, embedded files, image-only/scanned pages, or matches that cannot be safely mapped to page coordinates.

**OCR is intentionally not included.** Scanned/image-only PDFs and sensitive text that exists only inside an image are unsupported and fail closed where detected.

### DOCX

DOCX processing covers structured text including paragraphs, text split across runs, tables, headers/footers, supported note/comment XML, document metadata and external relationship targets.

Embedded/OLE payloads, macro payloads and image-only DOCX content fail closed where detected. OCR is not included.

### Archives

Native formats:

```text
.zip .tar .tgz .tar.gz .tar.bz2 .tbz2 .tar.xz .gz .bz2 .xz
```

With approved local/bundled 7-Zip:

```text
.7z .rar .lz .zst
```

Nested archives are subject to configured depth, extracted-size and file-count limits.

### Unsupported binary formats

Images, old `.doc`, PowerPoint, EVTX, PCAP, executables, databases and other unsupported binary formats are not treated as plain text. Unsupported content fails instead of being returned unchanged and mistaken for sanitized output.

## Output behavior

### One directly selected file

```text
incident.pdf
        ↓
incident_SANITIZED.pdf
Sanitization_Report_<job_id>.xlsx
```

### Folder or multi-file batch

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

## Excel audit report

Every successful job creates `Sanitization_Report_<job_id>.xlsx` with **Summary** and **Audit** sheets.

Audit columns:

- **File Name**
- **Match Type**
- **Occurrences**
- **Location**
- **Keywords** - configured Rules Library rule/regular expression

`Keywords` intentionally shows the configured rule unsanitized. The report does not reconstruct arbitrary original matched source values.

## Rules Library

Rules are regular expressions stored in `bad_words.txt`. Only Administrators can view or modify rule content through the application.

The IPv4 rule validates 0-255 octets and excludes common version/build contexts such as `version=1.2.3.4`, while an ambiguous bare value such as `1.2.3.4` remains masked for data-leak safety.

## Offline release build

Build on the target Ubuntu/Python/CPU combination:

```bash
bash scripts/build_offline_bundle.sh
```

Example output names:

```text
SanitizationApp-v2.1-Ubuntu22.04-Python3.10-x86_64-offline.tar.gz
SanitizationApp-v2.1-Ubuntu24.04-Python3.12-x86_64-offline.tar.gz
SanitizationApp-v2.1-Ubuntu26.04-Python3.14-x86_64-offline.tar.gz
```

If `.7z`/`.rar` support is required, an approved portable 7-Zip binary can be included at build time:

```bash
SANIT_7ZIP_BINARY=/approved/path/7zz bash scripts/build_offline_bundle.sh
```

## Offline installation

Extract the release built for the exact target OS/Python/architecture, then run:

```bash
sudo bash scripts/deploy_staging.sh --admin socadmin
```

or for manual virtual-environment installation:

```bash
PIP_NO_INDEX=1 bash scripts/install_offline.sh
```

The installer verifies the runtime manifest and wheel checksums, removes any old `.venv`, creates a fresh environment with the host's system Python, installs only from the local wheelhouse, and runs the environment verifier.

A wrong-OS/wrong-Python bundle is rejected before deployment.

## Expected production paths

```text
Application:   /opt/sanitization-app
Service user:  sanitizer
Environment:   /etc/sanitization-app/sanitization.env
Service:       sanitization-app.service
HTTPS port:    8443 by default
Job database:  /opt/sanitization-app/data/jobs.db
Rules file:    /opt/sanitization-app/bad_words.txt
App logs:      /opt/sanitization-app/logs/
```

Persistent configuration/state should be backed up according to local policy before upgrades or redeployments. Do not treat temporary uploads/outputs as long-term evidence storage.

## Production service

Gunicorn is configured in `gunicorn.conf.py`. v2.1 intentionally uses one Gunicorn worker because background-job progress remains process-local:

```text
SANIT_GUNICORN_WORKERS=1
SANIT_GUNICORN_THREADS=4
```

The supplied systemd unit performs two startup preflights:

1. standard-library OS/Python/bundle compatibility check;
2. full dependency/rules/application/UI environment verification.

Then it starts Gunicorn over HTTPS on the configured bind address.

See `DEPLOYMENT.md` for the complete production procedure.

## DevOps deployment checklist

For each release or OS upgrade:

1. Select the release artifact matching the exact Ubuntu/Python/architecture target.
2. Verify the release artifact/checksums according to the approved release process.
3. Back up persistent configuration/state required by local policy.
4. Stop the service before replacing/upgrading the application.
5. Run the offline deployment script without `--online`.
6. Confirm the installer rebuilt `.venv` and the environment verifier reports `RESULT: PASSED`.
7. Confirm `sudo systemctl status sanitization-app --no-pager` is healthy.
8. Confirm `https://127.0.0.1:8443/healthz` returns `{"status":"ok"}`.
9. Sign in as Administrator and verify the Dashboard Server & Runtime Overview matches the host.
10. Confirm Rules Library, User Management and Application Logs are accessible to Admin and blocked for Analyst.
11. Run a supported sample file and verify both sanitized output and Excel report download correctly.
12. Run a negative test with unsupported/image-only content and confirm it fails closed.
13. Review `journalctl` and local application logs for errors.
14. Run the real-server benchmark before accepting a new server build for production use.
15. Record the deployed artifact version/commit, Ubuntu version and Python version in the change record.

## Useful operational commands

```bash
# Environment validation
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/verify_environment.py

# Service status
sudo systemctl status sanitization-app --no-pager

# Recent service logs
sudo journalctl -u sanitization-app -n 200 --no-pager

# Follow service logs
sudo journalctl -u sanitization-app -f

# Validate Gunicorn configuration
/opt/sanitization-app/.venv/bin/gunicorn \
  --check-config \
  --config /opt/sanitization-app/gunicorn.conf.py \
  wsgi:application

# List configured local users
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --list-users
```

## Performance benchmark

Run the real-server baseline using synthetic SOC data and the active Rules Library:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/benchmark_performance.py \
  --sizes-mb 100 500 1024 2048
```

See `PERFORMANCE_BENCHMARK.md` for methodology.

## Automated validation

For each validated Ubuntu release, CI performs:

- system Python/version confirmation,
- complete locked dependency installation,
- environment and Rules Library validation,
- production UI/static asset validation,
- authentication/RBAC/CSRF/security tests,
- Admin User Management and Application Log API tests,
- live system-overview endpoint tests,
- text encoding tests,
- PDF/DOCX tests and fail-closed tests,
- single-file and folder/batch output tests,
- Excel audit/Keywords tests,
- archive safety tests,
- IPv4/version false-positive regression tests,
- 1 MB performance smoke test,
- Gunicorn configuration validation,
- OS-specific offline bundle build,
- offline bundle installation with Python package network access disabled.

## Future Ubuntu upgrade procedure

Do not simply upgrade the OS and reuse the old application virtual environment.

1. Back up application state and approved configuration.
2. Stop the service.
3. Upgrade Ubuntu.
4. Confirm the new OS and system Python versions.
5. Deploy the tested offline bundle built for that exact OS/Python/architecture.
6. Allow the deployment process to rebuild `.venv` from the bundled wheelhouse.
7. Run environment verification and staging acceptance.
8. Verify systemd and `/healthz`.
9. Run a representative sanitization job before returning to operational use.

See `OS_COMPATIBILITY_REVIEW.md` for root-cause analysis and failure-evidence commands.

## Security notes

- Restrict TCP/8443 to approved SOC/admin networks.
- Use an approved internal CA certificate in production.
- Keep runtime directories writable only by the service identity.
- Use systemd/Gunicorn rather than Flask's development server in production.
- Keep `SANIT_GUNICORN_WORKERS=1` for v2.1.
- OCR/image sanitization is not included; unsupported image-only content must not be treated as sanitized.
- The repository should contain no passwords, private TLS keys, secrets or sensitive SOC evidence.

## Support

Developed and maintained by Andy.
