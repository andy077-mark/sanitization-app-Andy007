# SOC Data Sanitization Platform v2.1 - Production Deployment & Validation

## Validated Ubuntu targets

The automated compatibility workflow validates the application against:

- Ubuntu 22.04 with system Python 3.10
- Ubuntu 24.04 with system Python 3.12

The workflow creates a clean virtual environment, installs pinned dependencies, runs the environment verifier, executes authentication/RBAC and functional smoke tests, validates the Gunicorn configuration, and proves that the offline bundle installs with package-network access disabled.

## Access model

v2.1 uses local application accounts stored as password hashes in `data/jobs.db`.

### Analyst

- Sign in/out
- Upload files and folders
- Start sanitization jobs
- Monitor processing
- View persistent job history
- Download sanitized packages and Excel reports
- View active-rule count

### Administrator

Includes all Analyst permissions plus:

- View Rules Library
- Add/edit/delete rules
- Bulk-save rules
- Clear rules
- Replace rules from TXT

Rules endpoints are protected server-side; hiding the UI is not the security control.

## Bootstrap accounts

Create the first administrator interactively from the application directory:

```bash
.venv/bin/python main.py --create-user socadmin --role admin
```

Create an analyst:

```bash
.venv/bin/python main.py --create-user analyst01 --role analyst
```

List accounts:

```bash
.venv/bin/python main.py --list-users
```

Reset, disable or enable an account:

```bash
.venv/bin/python main.py --reset-password analyst01
.venv/bin/python main.py --disable-user analyst01
.venv/bin/python main.py --enable-user analyst01
```

Passwords are entered interactively and are not placed on the command line or stored in plaintext.

## Security controls in v2.1

- Local password hashing using Werkzeug scrypt
- Analyst/Admin role authorization on server endpoints
- CSRF protection on uploads, logout and all rule changes
- `Secure`, `HttpOnly`, `SameSite=Strict` session cookies
- Stable session signing key across restarts
- CSP, frame-deny, no-sniff, referrer and permissions security headers
- Minimal unauthenticated `/healthz` endpoint
- Detailed `/health` available only after authentication
- Download links require both an authenticated session and job token
- Gunicorn debug/development server is not used by systemd

## Pre-deployment verification

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/verify_environment.py
```

A successful environment reports `RESULT: PASSED`.

For production/systemd startup, the unit sets `SANIT_REQUIRE_ADMIN=1`; the preflight check will refuse startup until at least one enabled Administrator exists.

## Functional test suite

```bash
pip install -r requirements-ci.txt
python -m pytest -q tests
```

The suite covers:

- Login/logout and invalid-login handling
- Analyst/Admin UI differences
- Server-side Admin authorization for Rules Library
- CSRF enforcement
- Security headers
- Authenticated `/health` and public minimal `/healthz`
- Multi-file upload as one job
- Folder-relative paths
- Sanitized ZIP package creation
- Excel audit report creation
- Persistent `/jobs` history and job creator
- Download authorization links
- Verification that the Excel report does not reproduce the test sensitive value
- Malicious ZIP path traversal rejection
- Correct `Failed` job persistence

## Building the air-gapped bundle

On an internet-connected builder with the same target OS/CPU architecture:

```bash
bash scripts/build_offline_bundle.sh
```

Output:

```text
dist/SanitizationApp-v2.1-offline-<arch>.tar.gz
dist/SanitizationApp-v2.1-offline-<arch>.tar.gz.sha256
```

If `.7z`/`.rar` support is required, provide an approved portable 7-Zip binary during the build:

```bash
SANIT_7ZIP_BINARY=/approved/path/7zz bash scripts/build_offline_bundle.sh
```

## Offline installation

```bash
tar -xzf SanitizationApp-v2.1-offline-<arch>.tar.gz
cd SanitizationApp-v2.1-offline-<arch>
bash scripts/install_offline.sh
```

The installer uses only:

```text
--no-index --find-links=./wheels
```

and does not contact PyPI.

## Gunicorn production model

The production WSGI configuration is `gunicorn.conf.py`.

Default settings:

```text
Bind:             0.0.0.0:8443
Worker class:     gthread
Gunicorn workers: 1
HTTP threads:     4
Timeout:          120 seconds
Graceful timeout: 30 seconds
Max requests:     1000 + jitter
TLS:              enabled
```

### Why one Gunicorn worker?

Sanitization jobs currently execute in background threads and live progress is held in process memory while persistent final status/history is written to SQLite. Multiple Gunicorn worker processes could route a progress request to a different process. Therefore v2.1 intentionally enforces:

```text
SANIT_GUNICORN_WORKERS=1
```

HTTP concurrency is controlled with:

```text
SANIT_GUNICORN_THREADS=4
```

Do **not** increase the worker count above 1 until job execution is moved to a dedicated external job queue/worker service.

Validate Gunicorn configuration:

```bash
.venv/bin/gunicorn --check-config --config gunicorn.conf.py wsgi:application
```

Manual production test:

```bash
bash scripts/start_production.sh
```

## systemd installation on Ubuntu

The supplied unit assumes:

```text
Application: /opt/sanitization-app
Service user: sanitizer
Configuration: /etc/sanitization-app/sanitization.env
```

Adjust the service file if your organization uses different paths.

### 1. Create service account

```bash
sudo useradd --system --home /opt/sanitization-app --shell /usr/sbin/nologin sanitizer 2>/dev/null || true
```

### 2. Place application under `/opt`

Example:

```bash
sudo mkdir -p /opt/sanitization-app
sudo cp -a . /opt/sanitization-app/
```

Install the offline/approved dependencies before enabling the service. Application code and `.venv` should normally remain owned by `root`, while runtime directories must be writable by the service account:

```bash
sudo mkdir -p /opt/sanitization-app/{uploads,outputs,logs,temp,data,certs}
sudo chown -R sanitizer:sanitizer /opt/sanitization-app/uploads \
  /opt/sanitization-app/outputs \
  /opt/sanitization-app/logs \
  /opt/sanitization-app/temp \
  /opt/sanitization-app/data \
  /opt/sanitization-app/certs
```

### 3. Create Administrator as the service identity

```bash
cd /opt/sanitization-app
sudo -u sanitizer .venv/bin/python main.py --create-user socadmin --role admin
```

Create analyst accounts the same way with `--role analyst`.

### 4. Install environment configuration

```bash
sudo mkdir -p /etc/sanitization-app
sudo cp /opt/sanitization-app/deploy/sanitization.env.example /etc/sanitization-app/sanitization.env
sudo chown root:sanitizer /etc/sanitization-app/sanitization.env
sudo chmod 640 /etc/sanitization-app/sanitization.env
```

Review the values before starting the service.

### 5. Install and enable systemd unit

```bash
sudo cp /opt/sanitization-app/deploy/sanitization-app.service /etc/systemd/system/sanitization-app.service
sudo systemctl daemon-reload
sudo systemctl enable --now sanitization-app
```

`enable --now` starts the service immediately **and** configures automatic startup after reboot.

### 6. Validate service

```bash
sudo systemctl status sanitization-app --no-pager
curl -k https://127.0.0.1:8443/healthz
```

Expected health response:

```json
{"status":"ok"}
```

View service logs:

```bash
sudo journalctl -u sanitization-app -n 200 --no-pager
sudo journalctl -u sanitization-app -f
```

Restart after a configuration/application change:

```bash
sudo systemctl restart sanitization-app
```

## Automatic restart behavior

The unit contains:

```text
Restart=on-failure
RestartSec=5s
```

If Gunicorn exits unexpectedly, systemd waits five seconds and restarts it. Graceful shutdown uses SIGTERM with a 45-second stop timeout.

## systemd sandboxing

The unit also enables:

- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `PrivateDevices=true`
- `ProtectSystem=full`
- `ProtectHome=true`
- Kernel/control-group protection
- SUID/SGID restriction
- `UMask=0077`
- Explicit writable application runtime directories only

## TLS certificate

The default Gunicorn configuration can use the application's self-signed certificate for staging. For production, replace it with an approved internal CA certificate.

Configure paths in `/etc/sanitization-app/sanitization.env`:

```text
SANIT_TLS_CERT=/path/to/approved/server.crt
SANIT_TLS_KEY=/path/to/approved/server.key
```

The `sanitizer` service account must be able to read the key, but the key should not be world-readable.

## Network restriction

Expose TCP/8443 only to the approved SOC/admin network using the host firewall and/or upstream network controls. Do not expose the application directly to the public internet.

## Staging acceptance checklist

Before production promotion, verify:

1. Unauthenticated access redirects to Sign In.
2. Invalid credentials are rejected.
3. Analyst can sanitize/download/view history.
4. Analyst cannot access Rules Library endpoints.
5. Administrator can manage Rules Library.
6. Logout invalidates the application session.
7. Browse Files works.
8. Browse Folder preserves relative structure.
9. Clear Selection works.
10. Start Sanitization creates one batch job.
11. Text/log sanitization removes configured test patterns.
12. `.xlsx` sanitization works.
13. ZIP processing works.
14. `.7z`/`.rar` works when approved 7-Zip is present.
15. Sanitized Package downloads successfully.
16. Excel Audit Report downloads successfully and contains no original sensitive values.
17. Job History survives application restart and records job creator.
18. Invalid/corrupt archives become `Failed` instead of hanging.
19. `/healthz` returns `status: ok`.
20. `systemctl restart sanitization-app` restores service successfully.
21. Service starts automatically after a test reboot.
22. Approved TLS certificate is presented in production.

## Remaining enterprise enhancement

Local authentication is suitable for controlled internal deployment. A later release can replace/local-map these accounts with organization AD/LDAP/SSO while retaining the same Analyst/Admin authorization model.
