# SOC Data Sanitization Platform v2.1 - Production Deployment & Validation

## Validated Ubuntu targets

The automated release workflow validates:

- Ubuntu 22.04 LTS / system Python 3.10
- Ubuntu 24.04 LTS / system Python 3.12
- Ubuntu 26.04 LTS / system Python 3.14

For each target the workflow creates a clean virtual environment, installs the complete locked dependency chain, runs the environment verifier, executes the functional/security test suite, validates Gunicorn, runs a benchmark smoke test, then builds and installs that target's offline release with Python package network access disabled.

See `OS_COMPATIBILITY_REVIEW.md` for the Ubuntu 22.04 -> 24.04 incident investigation and dependency-chain analysis.

## Critical OS-upgrade rule

**Never reuse the application's existing `.venv` across an Ubuntu release upgrade.**

Ubuntu releases can use different system Python minor versions. A virtual environment built for the previous Ubuntu/Python combination must not be treated as valid after an OS upgrade.

After an OS upgrade, deploy the offline release built for the new Ubuntu/Python/CPU target. The deployment process deletes and rebuilds `.venv` from the local release wheelhouse.

## Release artifact model

Each release artifact is OS/Python/architecture specific, for example:

```text
SanitizationApp-v2.1-Ubuntu22.04-Python3.10-x86_64-offline.tar.gz
SanitizationApp-v2.1-Ubuntu24.04-Python3.12-x86_64-offline.tar.gz
SanitizationApp-v2.1-Ubuntu26.04-Python3.14-x86_64-offline.tar.gz
```

Each bundle contains:

- application source, templates and local static UI assets,
- `requirements-lock.txt` with the complete direct + transitive runtime chain,
- all Python wheels required by that target,
- `WHEELS_SHA256SUMS.txt`,
- `RUNTIME_MANIFEST.json`,
- deployment and environment-verification scripts,
- staging acceptance and performance benchmark tools,
- `OS_COMPATIBILITY_REVIEW.md`,
- optional approved 7-Zip binary when supplied during release construction.

The target-server installer validates the manifest and checksums before installation.

## Internet / air-gap requirements

### Application target server

For the prepared offline release, Python dependencies are installed only from the bundled local wheelhouse using:

```text
PIP_NO_INDEX=1
--no-index
--find-links=<local wheels directory>
```

No Python package is downloaded from PyPI or another Python repository during offline installation. The application does not download packages, executables, fonts, JavaScript frameworks, analytics components or sanitization components during startup or runtime.

The UI uses local templates, CSS and JavaScript only.

The host must already provide its normal Ubuntu system `python3`, matching `python3-venv`, and systemd. In an air-gapped environment those OS components must be supplied by approved internal/offline Ubuntu media. Optional 7-Zip is needed only for `.7z`, `.rar` and related specialist formats; ZIP/TAR/GZ/BZ2/XZ use Python's standard library.

### Release builder

An approved connected build/CI host may access package repositories to collect wheels and construct the release artifact. This is not a production-server requirement.

## Complete Python dependency verification

`requirements-lock.txt` is the release source of truth. `scripts/verify_environment.py` checks every locked runtime package and exact version before production startup, as well as:

- active Rules Library syntax,
- writable runtime directories,
- SQLite access/schema,
- session secret,
- administrator presence when required,
- TLS certificate/key readiness,
- optional 7-Zip availability,
- disk space,
- release manifest compatibility when present,
- required production templates and static UI assets.

A missing or mismatched dependency or required production asset causes startup preflight failure.

## Current application UI and routes

The production interface includes:

- **Dashboard** - job KPIs, current job status, quick actions and live Server & Runtime Overview.
- **Sanitize Files** - file/folder selection, drag-and-drop, progress and result downloads.
- **Reports / History** - persistent job history, search, refresh, JSON export and output/report downloads.
- **Rules Library (Admin)** - add, edit, delete, save, clear and replace rules.
- **User Management (Admin)** - create Analyst/Admin users, enable/disable accounts and reset passwords.
- **Application Logs (Admin)** - read recent local `processing.log` entries.
- **About / System** - live runtime and compatibility information.

Important UI/runtime files:

```text
templates/index.html
templates/login.html
sanitization_v2/static/theme.css
sanitization_v2/static/login.css
sanitization_v2/static/dashboard.js
sanitization_v2/ui_extension.py
```

The live Server & Runtime Overview is detected from the actual host and reports values including hostname, Ubuntu/platform, Python version, CPU model, logical CPUs, memory, free disk and disk utilization.

Relevant authenticated endpoints include:

```text
/health
/system-info
/rules/status
/jobs
```

Administrator-only endpoints include:

```text
/admin/users
/admin/users/create
/admin/users/toggle
/admin/users/reset-password
/admin/logs
/bad_words
/rules/*
```

These endpoints are protected server-side by authentication/RBAC; UI visibility is not the security boundary.

## Access model

### Analyst

- Sign in/out
- Upload files/folders
- Start sanitization jobs
- Monitor jobs and history
- Download sanitized output and Excel reports
- View active-rule count
- View live system/runtime information

### Administrator

Includes all Analyst capabilities plus:

- Rules Library administration
- Create Analyst/Admin users
- Enable/disable users
- Reset local user passwords
- View recent local application logs

## Supported sanitization content

Supported content includes text/log/config formats, XLS/XLSX, text-based PDF, DOCX structured text, and supported archives.

OCR is not included. Images, scanned/image-only PDFs and other unsupported binary formats fail closed rather than being treated as sanitized.

## Output modes

A directly selected single file returns a direct `*_SANITIZED.<ext>` output plus a separate Excel report.

Folder and multi-file jobs return a ZIP package preserving relative paths, plus the Excel report as a separate download.

The Audit sheet columns are exactly:

```text
File Name | Match Type | Occurrences | Location | Keywords
```

`Keywords` intentionally stores the configured rule text, not reconstructed arbitrary source values.

## Recommended offline deployment

Extract the release built for the exact target OS/Python/architecture, then run:

```bash
sudo bash scripts/deploy_staging.sh --admin socadmin
```

The script:

1. confirms Python 3.10+ and `python3-venv`,
2. validates the release manifest against the host,
3. preserves application runtime state,
4. verifies bundled wheel checksums,
5. deletes the old `.venv`,
6. creates a fresh venv with the target system Python,
7. installs only from the local locked wheelhouse,
8. creates/uses persistent application configuration,
9. verifies the exact installed environment,
10. installs/restarts the systemd service,
11. probes `/healthz` using Python's standard library rather than requiring curl/wget.

For a connected **staging-only source checkout** without an offline wheelhouse, `--online` remains an explicit opt-in:

```bash
sudo bash scripts/deploy_staging.sh --admin socadmin --online
```

Production/air-gapped deployment should use the prepared offline artifact and omit `--online`.

## Manual offline installation

```bash
PIP_NO_INDEX=1 bash scripts/install_offline.sh
```

This validates the bundle/host combination, verifies wheel SHA-256 checksums, rebuilds `.venv`, installs from local wheels only and runs environment verification.

## Bootstrap and user administration

Create an administrator interactively:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --create-user socadmin --role admin
```

Create an analyst:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --create-user analyst01 --role analyst
```

List users:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --list-users
```

Reset, disable or enable an account from CLI when needed:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --reset-password analyst01

sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --disable-user analyst01

sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --enable-user analyst01
```

Equivalent day-to-day user administration is also available to Administrators through the web UI.

Passwords are entered interactively or through the protected Admin UI and are never returned by the API or stored in plaintext.

## Production service

Expected paths:

```text
Application:   /opt/sanitization-app
Service user:  sanitizer
Environment:   /etc/sanitization-app/sanitization.env
Service:       sanitization-app.service
HTTPS port:    8443 by default
```

The systemd unit performs:

```text
ExecStartPre=/usr/bin/python3 .../scripts/check_bundle_compatibility.py .../RUNTIME_MANIFEST.json
ExecStartPre=/opt/sanitization-app/.venv/bin/python .../scripts/verify_environment.py
ExecStart=/opt/sanitization-app/.venv/bin/gunicorn --config .../gunicorn.conf.py wsgi:application
```

The first preflight uses only the Python standard library so it can report a stale/wrong release bundle even if the old virtual environment is broken.

## Gunicorn model

v2.1 intentionally requires:

```text
SANIT_GUNICORN_WORKERS=1
SANIT_GUNICORN_THREADS=4
```

Background job progress is process-local, so do not increase the Gunicorn worker count until job execution moves to an external worker queue.

Validate configuration with:

```bash
/opt/sanitization-app/.venv/bin/gunicorn \
  --check-config \
  --config /opt/sanitization-app/gunicorn.conf.py \
  wsgi:application
```

## TLS

The self-signed certificate is suitable only for staging. Production should use an approved internal CA certificate configured through:

```text
SANIT_TLS_CERT=/path/to/approved/server.crt
SANIT_TLS_KEY=/path/to/approved/server.key
```

Restrict TCP/8443 to approved SOC/admin networks.

## Health and system information

Check the service:

```bash
sudo systemctl status sanitization-app --no-pager
```

Minimal unauthenticated service probe:

```text
https://127.0.0.1:8443/healthz
```

Expected response:

```json
{"status":"ok"}
```

Authenticated operational health and runtime information are available through:

```text
/health
/system-info
```

The dashboard uses these endpoints to populate the live Server & Runtime Overview.

## Application and service logs

Systemd/Gunicorn logs:

```bash
sudo journalctl -u sanitization-app -n 200 --no-pager
sudo journalctl -u sanitization-app -f
```

Application processing log:

```text
/opt/sanitization-app/logs/processing.log
```

Administrators can also view recent `processing.log` entries in the **Application Logs** page of the web UI.

## Staging acceptance

Run the supplied acceptance checker separately with an Administrator and Analyst account:

```bash
/opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/staging_acceptance.py \
  --url https://127.0.0.1:8443 --username <admin> --role admin

/opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/staging_acceptance.py \
  --url https://127.0.0.1:8443 --username <analyst> --role analyst
```

Also manually verify representative `.log`, `.csv`, `.xlsx`, text-based `.pdf`, `.docx`, direct single-file output, folder/batch output, Excel report, and unsupported scanned/image content fail-closed behavior.

### UI acceptance checks

Before go-live, verify that all current controls operate correctly:

- Login and Sign Out
- Dashboard navigation
- Sanitize Files / Choose Files / Choose Folder
- Clear Selection / Start Sanitization
- Sanitized Output download
- Excel Audit Report download
- Reports/History refresh, search and JSON export
- Rules Library add/edit/delete/save/clear/replace actions for Admin
- User Management create/enable/disable/reset-password actions for Admin
- Application Logs refresh for Admin
- Server & Runtime Overview refresh
- Analyst cannot access Admin-only endpoints or controls

Confirm that the dashboard displays the actual target server information, for example the expected hostname, Ubuntu 24.04, Python 3.12.x, CPU details, logical CPUs, memory and disk utilization on the Ubuntu 24.04 target.

## Performance baseline

After staging acceptance:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/benchmark_performance.py \
  --sizes-mb 100 500
```

Then, if server capacity/disk is healthy:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/benchmark_performance.py \
  --sizes-mb 1024 2048
```

See `PERFORMANCE_BENCHMARK.md`.

## Future Ubuntu upgrade procedure

1. Back up `data/jobs.db`, the Rules Library, approved configuration and TLS material.
2. Stop `sanitization-app`.
3. Upgrade Ubuntu.
4. Record `cat /etc/os-release` and `python3 --version`.
5. Do **not** start the old application venv as the production runtime.
6. Deploy the offline bundle built/tested for the new Ubuntu/Python/architecture.
7. Let deployment rebuild `.venv` from the bundled wheelhouse.
8. Run `scripts/verify_environment.py`.
9. Run Admin and Analyst staging acceptance.
10. Validate systemd, `/healthz`, `/health`, `/system-info`, representative sanitization and performance as appropriate.

## Evidence to capture before rollback if an upgrade fails

```bash
cat /etc/os-release
python3 --version
/opt/sanitization-app/.venv/bin/python --version || true
sudo systemctl status sanitization-app --no-pager
sudo journalctl -u sanitization-app -b --no-pager -n 300
sudo -u sanitizer /usr/bin/python3 \
  /opt/sanitization-app/scripts/check_bundle_compatibility.py \
  /opt/sanitization-app/RUNTIME_MANIFEST.json
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/verify_environment.py || true
```

Capture these records before rolling back so a future incident can be proven rather than inferred.

## Security hardening

The supplied systemd unit uses restricted runtime permissions and controls including `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectSystem`, `ProtectHome`, kernel/control-group protection, SUID/SGID restriction and `UMask=0077`.

Additional production requirements:

- restrict TCP/8443 to approved SOC/admin networks,
- use an approved internal CA certificate,
- protect `/etc/sanitization-app/sanitization.env`, TLS private keys and application runtime data,
- never store credentials or sensitive SOC evidence in the repository,
- keep `SANIT_GUNICORN_WORKERS=1` for v2.1,
- use the offline release package rather than `--online` for production,
- do not treat unsupported image/scanned content as sanitized.

## Remaining enterprise enhancements

Potential later enhancements include login rate limiting/lockout, richer administrator audit events, AD/LDAP/SSO integration, dedicated external job workers/queue, backup/restore automation and further format-specific sanitizers where a defensible fail-safe design is available.
