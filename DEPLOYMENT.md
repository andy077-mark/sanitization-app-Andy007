# SOC Data Sanitization Platform v2 - Deployment & Validation

## Supported Ubuntu targets

The automated compatibility workflow validates the application against:

- Ubuntu 22.04 with the system Python 3.10 runtime
- Ubuntu 24.04 with the system Python 3.12 runtime

The workflow creates a fresh virtual environment on each OS, installs the pinned dependencies, runs the environment verifier, executes the functional smoke tests, and proves that the generated offline bundle can be installed with package-network access disabled.

## Pre-deployment verification

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/verify_environment.py
```

A successful environment should report `RESULT: PASSED`.

7-Zip is optional for ZIP/TAR/GZ/BZ2/XZ because those formats have safe Python implementations. A local or bundled 7-Zip binary is required for `.7z`, `.rar` and specialist formats.

## Functional test suite

Install the CI test dependency and run:

```bash
pip install -r requirements-ci.txt
python -m pytest -q tests
```

The suite covers:

- UI/button contract and `/health`
- Rules add/edit/remove/save validation
- Multi-file upload as one job
- Folder-relative paths
- Sanitized ZIP package creation
- Excel audit report creation
- Persistent `/jobs` history
- Download authorization links
- Verification that the Excel audit report does not reproduce the test sensitive value
- Malicious ZIP path traversal rejection
- Correct `Failed` job persistence

## Building an air-gapped bundle

Build the bundle on an internet-connected machine with the same target OS/CPU architecture:

```bash
bash scripts/build_offline_bundle.sh
```

Output:

```text
dist/SanitizationApp-v2-offline-<arch>.tar.gz
dist/SanitizationApp-v2-offline-<arch>.tar.gz.sha256
```

The bundle contains a local Python wheelhouse and can be transferred to the air-gapped server.

If `.7z`/`.rar` support is required, supply an approved portable 7-Zip binary when building:

```bash
SANIT_7ZIP_BINARY=/approved/path/7zz bash scripts/build_offline_bundle.sh
```

## Installing on the air-gapped server

Extract the bundle and run:

```bash
tar -xzf SanitizationApp-v2-offline-<arch>.tar.gz
cd SanitizationApp-v2-offline-<arch>
bash scripts/install_offline.sh
```

The installer deliberately uses:

```text
--no-index --find-links=./wheels
```

so no Python package repository is contacted during installation.

## Staging acceptance checklist

Before production promotion, verify:

1. Dashboard loads over HTTPS.
2. Browse Files works.
3. Browse Folder preserves relative folder structure.
4. Clear Selection works.
5. Start Sanitization creates one batch job.
6. Text/log sanitization removes configured test patterns.
7. `.xlsx` sanitization works.
8. ZIP processing works.
9. `.7z`/`.rar` works when an approved 7-Zip binary is present.
10. Sanitized Package downloads successfully.
11. Excel Audit Report downloads successfully and contains no original sensitive values.
12. Job History survives an application restart.
13. Invalid/corrupt archives become `Failed` jobs instead of hanging in `Processing`.
14. Rules Add/Edit/Delete/Save/Replace actions work.
15. `/health` reports `status: ok`.

## Production items still required

Do not expose the application broadly until these are completed:

- Authentication and role-based authorization, especially for Rules Library administration
- Approved internal TLS certificate instead of the self-signed testing certificate
- Production WSGI service and `systemd` service definition on Ubuntu
- Final organization-specific retention and archive-size limits
- Staging acceptance sign-off
