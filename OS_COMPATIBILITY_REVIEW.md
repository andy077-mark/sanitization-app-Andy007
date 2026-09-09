# Log Sanitization Application - Ubuntu Compatibility Review

## Executive conclusion

The current application code and pinned Python dependency chain are compatible with Ubuntu 22.04, Ubuntu 24.04 and Ubuntu 26.04 LTS when installed into a clean virtual environment built for the system Python supplied by that OS.

The application failure observed immediately after an in-place Ubuntu 22.04 -> 24.04 upgrade is therefore not reproduced as an application-library incompatibility. The strongest application-level root-cause candidate is reuse of the Ubuntu 22.04 Python 3.10 virtual environment after Ubuntu 24.04 changed the system default Python to 3.12.

A Python virtual environment is tied to the Python minor version and interpreter layout that created it. It must not be carried across an operating-system upgrade that changes Python from 3.10 to 3.12. The existing production service starts the application through `/opt/sanitization-app/.venv/bin/python` and Gunicorn inside that environment, so a stale/broken virtual environment can prevent service startup even when the application source itself is compatible.

Because the failed Ubuntu 24.04 environment was rolled back and its original journal/package/error evidence is not currently available in this repository, the exact historical error cannot be proven retrospectively from source code alone. The conclusion above is the most likely root cause based on the dependency chain, deployment design, OS Python change and successful clean-room Ubuntu 24.04 validation.

## Supported OS / Python matrix

| Ubuntu | Default Python used by validation | Status |
|---|---:|---|
| 22.04 LTS | 3.10 | Automated compatibility test |
| 24.04 LTS | 3.12 | Automated compatibility test |
| 26.04 LTS | 3.14 | Automated compatibility test |

Each target is tested independently rather than assuming that a virtual environment created on one Ubuntu/Python release will work on another.

## Complete Python runtime dependency chain

The release uses `requirements-lock.txt` as the authoritative complete runtime lock. It contains both direct and transitive runtime packages:

| Package | Locked version | Purpose |
|---|---:|---|
| Flask | 3.1.3 | Web application framework |
| Werkzeug | 3.1.8 | WSGI/auth/web utilities used by Flask/app |
| Jinja2 | 3.1.6 | HTML templates |
| MarkupSafe | 3.0.3 | Jinja2 escaping dependency |
| itsdangerous | 2.2.0 | Flask signing dependency |
| click | 8.5.0 | Flask CLI dependency |
| blinker | 1.9.0 | Flask signals dependency |
| cryptography | 50.0.1 | Local TLS certificate generation/crypto |
| cffi | 2.1.1 | cryptography native interface dependency |
| pycparser | 3.0 | cffi dependency |
| openpyxl | 3.1.5 | XLSX processing/reporting |
| et_xmlfile | 2.0.0 | openpyxl dependency |
| xlrd | 2.0.2 | legacy XLS reading |
| xlwt | 1.3.0 | legacy XLS writing |
| PyMuPDF | 1.26.4 | PDF text extraction/redaction |
| python-docx | 1.2.0 | DOCX validation/document handling |
| lxml | 6.1.3 | DOCX XML processing dependency |
| typing_extensions | 4.16.0 | python-docx compatibility dependency |
| gunicorn | 23.0.0 | Production WSGI server |
| packaging | 26.3 | Gunicorn/runtime version utility dependency |

`requirements.txt` continues to list direct application dependencies for maintainability, while release construction and environment verification use the complete lock.

## OS-level dependencies

The application release itself does not use `apt` during startup or runtime. The target Ubuntu image must provide:

- `python3` matching the target release (3.10 on 22.04, 3.12 on 24.04, 3.14 on 26.04),
- `python3-venv` for creation of the local application virtual environment,
- standard Ubuntu runtime libraries required by the selected Python/native wheels,
- systemd for the production service,
- optional 7-Zip only when `.7z`, `.rar` or specialist archive support is required.

ZIP/TAR/GZ/BZ2/XZ support uses Python's standard library and does not require 7-Zip.

If the production environment is air-gapped, `python3-venv` and any optional 7-Zip package/binary must come from approved internal/offline OS media. The application installer does not attempt to contact Ubuntu repositories.

## Internet / external dependency behavior

### Build environment

An approved connected build/CI environment may download packages while constructing a release artifact. That is a release-engineering activity, not target-server runtime behavior.

### Target installation from the offline bundle

The generated OS/Python-specific bundle contains:

- application source,
- `requirements-lock.txt`,
- all required Python wheels for that OS/Python/architecture,
- wheel SHA-256 checksums,
- runtime compatibility manifest,
- deployment, verification and acceptance scripts,
- optional bundled 7-Zip when supplied at release-build time.

Offline installation runs pip with both `PIP_NO_INDEX=1` and `--no-index --find-links=<local wheelhouse>`. No Python package is downloaded from PyPI or another external repository.

### Startup / runtime

The application does not download Python packages or executables during startup/runtime. The 7-Zip helper only searches bundled/local/system paths and explicitly never downloads 7-Zip. No HTTP client dependency such as `requests` is part of the runtime lock.

## Controls added after the Ubuntu upgrade incident

1. **Complete dependency lock** - direct and transitive versions are pinned in `requirements-lock.txt`.
2. **OS/Python-specific release artifacts** - bundle names include Ubuntu release, Python minor version and CPU architecture.
3. **Runtime manifest** - each offline release records its expected Ubuntu/Python/architecture combination and complete dependency set.
4. **Wrong-bundle rejection** - installation refuses to use, for example, an Ubuntu 22.04/Python 3.10 bundle on Ubuntu 24.04/Python 3.12.
5. **OS-upgrade startup preflight** - systemd checks the release manifest before importing third-party packages. A stale release after an OS upgrade now fails with a clear message instructing the operator to deploy the matching bundle instead of producing an opaque broken-venv/import failure.
6. **Wheel integrity verification** - bundled wheels are verified against SHA-256 checksums before offline installation.
7. **Complete environment verification** - every locked runtime package and active sanitization regex is validated before production startup.
8. **Three-release CI matrix** - functional tests, PDF/DOCX tests, RBAC/security tests, benchmark smoke test and Gunicorn config checks run on Ubuntu 22.04, 24.04 and 26.04.
9. **Per-OS offline proof** - a separate offline bundle is built and installed with Python package network access disabled on each supported OS/Python target.

## Required procedure for future Ubuntu upgrades

Do not carry the existing `.venv` across an Ubuntu release upgrade.

Recommended sequence:

1. Back up application state (`data/jobs.db`, rules/configuration and approved TLS material).
2. Stop the sanitization service.
3. Upgrade the Ubuntu OS.
4. Confirm the new OS and system Python versions.
5. Deploy the offline Sanitization App bundle built for that exact Ubuntu/Python/architecture target.
6. The deployment script deletes/rebuilds `.venv` from the local, checksummed wheelhouse only.
7. Run `scripts/verify_environment.py`.
8. Run staging acceptance as Administrator and Analyst.
9. Validate `/healthz` and systemd status.
10. Run a representative sanitization test before returning the service to operational use.

## Evidence to collect if a future OS upgrade fails

Before rollback, capture:

```bash
cat /etc/os-release
python3 --version
/opt/sanitization-app/.venv/bin/python --version || true
sudo systemctl status sanitization-app --no-pager
sudo journalctl -u sanitization-app -b --no-pager -n 300
sudo -u sanitizer /usr/bin/python3 /opt/sanitization-app/scripts/check_bundle_compatibility.py /opt/sanitization-app/RUNTIME_MANIFEST.json
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python /opt/sanitization-app/scripts/verify_environment.py || true
```

Those records are required to distinguish a stale Python environment from permissions, TLS, filesystem, systemd-hardening or another host-level change.

## Current assessment

No pinned application runtime library has been identified as inherently incompatible with Ubuntu 24.04. Clean Ubuntu 24.04/Python 3.12 validation installs the full locked dependency chain and runs the application test suite successfully. The prior failure is most consistent with deployment/runtime state being carried across the OS/Python upgrade rather than with the application source being incompatible with Ubuntu 24.04.
