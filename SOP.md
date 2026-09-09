# Log Sanitization Application v2.1 - Standard Operating Procedure (SOP)

**Document ID:** SOP-SOC-SAN-001  
**Version:** 1.0  
**Effective date:** 09 September 2026  
**System:** SOC Data Sanitization Platform / Log Sanitization Application v2.1  
**Document owner:** SOC Operations  
**Prepared by:** Andy  
**Classification:** Internal  
**Review cycle:** At least annually and after any major application, operating-system, dependency, security, or workflow change

> This SOP governs day-to-day operation of the Log Sanitization Application. `README.md` provides the product overview, `DEPLOYMENT.md` is the DevOps deployment/runbook, `OS_COMPATIBILITY_REVIEW.md` covers Ubuntu upgrade compatibility, and `PERFORMANCE_BENCHMARK.md` covers performance testing.

---

## 1. Purpose

The purpose of this SOP is to define a controlled and repeatable process for sanitizing sensitive SOC data before logs, spreadsheets, documents, folders, or archives are shared outside their original handling context.

The application replaces configured sensitive matches with `X` characters and creates:

1. a sanitized output; and
2. a separate Excel audit report.

The SOP also defines user responsibilities, validation requirements, fail-closed handling, Rules Library administration, user administration, routine health checks, troubleshooting, retention, upgrade controls, and escalation requirements.

## 2. Scope

This SOP applies to:

- SOC Analysts using the application to sanitize supported content;
- Administrators maintaining local users and sanitization rules;
- SOC/DevOps personnel supporting the service;
- staging and production instances of the Log Sanitization Application v2.1.

This SOP does not authorize users to bypass organizational data-classification, evidence-handling, privacy, or information-sharing requirements.

## 3. Current production reference

The application is designed to detect runtime values from the host. The current Ubuntu 24.04 target should present information similar to:

```text
Host:             soc-sanitizer-02
Platform:         Ubuntu 24.04
Python:           3.12.x
CPU:              Intel Xeon ...
Logical CPUs:     8
Memory:           Detected from host
Free disk:        Detected from host
Disk utilization: Detected from host
```

The values displayed under **Dashboard -> Server & Runtime Overview** are authoritative for the running host and must not be assumed from documentation.

## 4. Roles and responsibilities

### 4.1 Analyst

Analysts may:

- sign in and sign out;
- upload supported files and folders;
- start sanitization jobs;
- monitor job progress;
- review job history;
- download sanitized output and Excel audit reports;
- view the active-rule count;
- view server/runtime information.

Analysts must verify the sanitized output before sharing it.

### 4.2 Administrator

Administrators have all Analyst capabilities and may additionally:

- add, edit, delete, save, clear, and replace sanitization rules;
- create Analyst and Administrator users;
- enable or disable users;
- reset local user passwords;
- review recent application logs;
- support troubleshooting and validation.

### 4.3 DevOps / system support

DevOps/system support is responsible for:

- deploying only the correct offline release for the target Ubuntu/Python/architecture combination;
- maintaining the service, TLS, firewall, disk capacity, and approved server configuration;
- ensuring the service starts with a clean compatible virtual environment after OS upgrades;
- protecting application state and configuration;
- running deployment, health, acceptance, and performance checks after infrastructure changes.

## 5. Mandatory security principles

1. Use only authorized SOC accounts. Do not share credentials.
2. Do not place passwords, private TLS keys, credentials, or sensitive evidence in the GitHub repository.
3. Do not move an unsanitized source file outside its approved environment merely because a sanitization job was started.
4. A job is not considered complete until the sanitized output and audit report have been reviewed.
5. Unsupported content must be treated as **not sanitized**.
6. Images and scanned/image-only PDFs are not supported because OCR is intentionally not included.
7. The application is offline-first. Production installation, startup, and runtime must not depend on downloading Python packages or components from the internet.
8. Restrict TCP/8443 to approved SOC/admin networks and use an approved internal CA certificate in production.
9. Keep `SANIT_GUNICORN_WORKERS=1` for v2.1 because job progress/state remains process-local.
10. Do not reuse the old `.venv` after an Ubuntu release upgrade.

## 6. Supported content

### 6.1 Text and SOC/config formats

Supported text-like formats include:

```text
.txt .log .csv .tsv .json .jsonl .ndjson
.xml .yaml .yml .ini .cfg .conf .config .properties .env
.md .rst .html .htm .css .js .ts .py
.ps1 .psm1 .psd1 .sh .bash .zsh .bat .cmd .vbs
.sql .reg .inf .service .socket .timer .rules .list .hosts
```

Supported text encodings include UTF-8, UTF-8 BOM, UTF-16 LE, UTF-16 BE, and Windows-1252.

### 6.2 Spreadsheets

- `.xlsx`
- `.xls`

### 6.3 PDF

Text-based PDFs are supported using permanent PDF redaction. Password-protected PDFs, PDFs with embedded files, image-only/scanned pages, or content that cannot be safely mapped for redaction fail closed.

### 6.4 DOCX

Structured DOCX text is supported, including paragraphs, text split across runs, tables, headers/footers, supported note/comment XML, metadata, and external relationship targets. Embedded/OLE payloads, macro payloads, and image-only DOCX content fail closed where detected.

### 6.5 Archives

Native archive support includes:

```text
.zip .tar .tgz .tar.gz .tar.bz2 .tbz2 .tar.xz .gz .bz2 .xz
```

With an approved local/bundled 7-Zip binary, additional formats can include:

```text
.7z .rar .lz .zst
```

### 6.6 Unsupported content

Examples include images, scanned/image-only PDFs, old `.doc`, PowerPoint, EVTX, PCAP, executables, databases, and other unsupported binary formats. These must not be treated as sanitized.

## 7. Standard operating limits

Unless changed through approved environment configuration, the current application defaults include:

```text
Maximum upload request:       2048 MB (2 GB)
Maximum selected files:       10,000
Maximum extracted archive:    4096 MB (4 GB)
Maximum extracted files:      10,000
Maximum archive depth:        5
Archive timeout:              300 seconds
Output/upload/temp retention: 1 day
Job history retention:        90 days
```

Do not use the application as long-term evidence storage. Export/retain required sanitized evidence and audit reports according to organizational policy.

## 8. Start-of-shift / pre-use checks

Before processing sensitive data, the operator should confirm:

1. Open the application through the approved internal URL.
2. Sign in with the assigned account.
3. Confirm the dashboard shows **Local / Secure**.
4. Review **Server & Runtime Overview** and confirm the expected host/platform are displayed.
5. Confirm **Current Job** is not showing an unexpected active or failed process.
6. Confirm the **Rules Library active count** loads successfully.
7. If the application appears unavailable or abnormal, stop and follow Section 18 before uploading sensitive files.

Administrators or support personnel may additionally check:

```bash
sudo systemctl status sanitization-app --no-pager
```

and confirm `/healthz` returns:

```json
{"status":"ok"}
```

## 9. Standard sanitization procedure

### 9.1 Prepare the source

1. Confirm the source is authorized for sanitization.
2. Confirm the file type is supported.
3. If processing a folder, ensure it contains only data intended for the same sanitization activity.
4. Do not rename or modify original evidence unnecessarily before sanitization.
5. Keep the original in its approved location until the sanitized copy has been validated.

### 9.2 Select content

1. Open **Sanitize Files**.
2. Use **Choose Files**, **Choose Folder**, or drag-and-drop.
3. Review the selected-file list.
4. Confirm filenames, folder paths, file count, and total size.
5. Remove unintended files before processing.

### 9.3 Start sanitization

1. Select **Start Sanitization**.
2. Monitor upload progress.
3. Monitor the job status and current file.
4. Do not close the session until the job reaches **Done** or **Failed** unless operationally necessary.

### 9.4 Completion

A successful job displays:

- job ID;
- status **Done**;
- replacement count;
- sanitized output download;
- Excel audit report download.

A failed job must be treated as **not sanitized**.

## 10. Output modes

### 10.1 One directly selected file

A single directly selected file is returned directly:

```text
security.log
      -> security_SANITIZED.log
      -> Sanitization_Report_<job_id>.xlsx
```

A directly selected archive is returned as the sanitized/repacked archive with `_SANITIZED` in the filename.

### 10.2 Folder or multiple files

Folder and multi-file jobs are returned as a ZIP package preserving relative paths:

```text
Sanitized_Package_<job_id>.zip
├── Sanitized_Files/
│   └── <preserved relative paths>
└── Sanitization_Report_<job_id>.xlsx
```

The Excel report is also available separately.

## 11. Mandatory output validation before sharing

Before any sanitized output is shared, the operator must:

1. Download the sanitized output.
2. Download the Excel audit report.
3. Confirm the job ID in the report/history matches the expected job.
4. Confirm the expected file(s) are present.
5. Open the sanitized file(s) and confirm they are readable and structurally usable.
6. Review known sensitive examples and verify they were replaced with `X` characters.
7. Confirm expected non-sensitive content remains usable.
8. Review the Excel report for unexpected match categories or unusually high/low counts.
9. If the output appears over-sanitized or under-sanitized, do not share it. Escalate for Rules Library review.
10. Share only the validated sanitized copy, never the original source by mistake.

For high-sensitivity evidence, perform a second-person review when required by local policy.

## 12. Excel audit report

Every successful job creates `Sanitization_Report_<job_id>.xlsx` containing **Summary** and **Audit** sheets.

The Audit columns are exactly:

```text
File Name | Match Type | Occurrences | Location | Keywords
```

Important behavior:

- `Keywords` shows the configured rule/regular expression that triggered the match.
- The configured rule is intentionally not masked in the audit report.
- The report does not reconstruct arbitrary original matched values.
- The sanitized source output continues to replace matched source values with `X` characters.

The audit report must be protected according to the same or higher classification requirements applicable to its rule content and operational context.

## 13. Version-number and IPv4 handling

The IPv4 sanitization logic validates IPv4 octets and avoids common software-version contexts such as:

```text
version=1.2.3.4
Version 7.4.2.1
build=3.12.4.1
release:2.5.6.7
v1.2.3.4
```

Real IPv4 values such as `src=10.20.30.40` remain subject to sanitization.

An ambiguous bare dotted value such as `1.2.3.4` is still treated conservatively and may be masked. If a legitimate application repeatedly produces ambiguous version strings, capture examples and submit them for controlled rule review rather than weakening the rule ad hoc.

## 14. Reports / History procedure

Use **Reports / History** to:

- review recent jobs;
- search job history;
- refresh job status;
- export job history to JSON;
- download available sanitized output;
- download available Excel audit reports.

Job history is operational metadata and is not a substitute for formal evidence retention.

## 15. Rules Library administration

Only Administrators may modify rules.

### 15.1 Before changing a rule

1. Record the business/security reason for the change.
2. Capture at least one positive example that should be masked.
3. Capture at least one negative example that must remain unchanged.
4. Confirm the change will not unnecessarily expose sensitive data.

### 15.2 Change procedure

Use **Rules Library** to add, edit, delete, bulk-save, clear, or replace rules.

After any material rule change:

1. run a controlled test file;
2. verify both masking and false-positive behavior;
3. review the Excel audit report;
4. confirm no supported test file is corrupted;
5. record the change according to local change-control requirements.

Do not clear or replace the entire Rules Library in production without an approved backup and change record.

## 16. User Management procedure

Administrators may create local Analyst/Admin users, enable/disable accounts, and reset passwords.

Requirements:

- usernames must meet application validation rules;
- passwords must be at least 12 characters;
- do not share passwords in email, tickets, chat, scripts, or command-line arguments;
- disable accounts that are no longer authorized;
- retain at least one enabled Administrator account;
- never disable the final active Administrator.

CLI administration is also available to authorized support staff through `main.py` when required.

## 17. Application Logs and system overview

Administrators can review recent `processing.log` entries in **Application Logs**.

Local application log path:

```text
/opt/sanitization-app/logs/processing.log
```

Systemd/Gunicorn logs:

```bash
sudo journalctl -u sanitization-app -n 200 --no-pager
sudo journalctl -u sanitization-app -f
```

Use **About / System** or **Server & Runtime Overview** to confirm host, Ubuntu/platform, Python version, CPU, logical CPUs, memory, free disk, and disk utilization.

## 18. Failed jobs and troubleshooting

If a job fails:

1. Do not share the output as sanitized.
2. Note the job ID and error message.
3. Confirm whether the file type is supported.
4. Check whether the file is password-protected, image-only/scanned, macro-enabled, contains unsupported embedded data, or is an unsupported binary.
5. Confirm upload/extraction size and archive-depth limits have not been exceeded.
6. Retry only when the cause is understood and the retry is safe.
7. Escalate persistent or unexplained failures to the Administrator/DevOps team.

Support personnel should capture, where appropriate:

```bash
sudo systemctl status sanitization-app --no-pager
sudo journalctl -u sanitization-app -n 200 --no-pager
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/verify_environment.py
```

Do not paste sensitive source content into external troubleshooting channels.

## 19. Service-unavailable procedure

If the application cannot be reached:

1. Stop attempting uploads.
2. Confirm network reachability according to local procedures.
3. Check service status.
4. Review recent service logs.
5. Confirm disk space is not exhausted.
6. Run the environment verifier if authorized.
7. Escalate before making package/dependency changes on the production server.

Do not run `pip install` from the internet on the production server to fix an outage.

## 20. Retention and housekeeping

Current defaults are:

- output/upload/temp files: 1 day;
- job-history database records: 90 days.

These values can be overridden by approved environment configuration.

Operators must download any sanitized output/audit report that must be retained before application cleanup removes it. Formal evidence retention must follow organizational policy outside the application's temporary output area.

Application logs use local rotation; monitor disk usage and retain/export logs only according to approved policy.

## 21. Routine operational checks

### Daily / each shift

- confirm service/UI availability;
- confirm expected server/runtime information;
- review failed jobs;
- verify sufficient disk capacity for planned large jobs;
- confirm Rules Library count loads successfully.

### Weekly

- review recurring failed jobs and false-positive reports;
- review disabled/unused accounts;
- review application/service logs for repeated errors;
- confirm backup/retention processes required by local policy are functioning.

### Monthly or after major change

- run representative functional tests;
- review Rules Library appropriateness;
- review account access;
- review disk utilization and job volumes;
- run performance baseline when infrastructure or application performance has materially changed.

## 22. Performance validation

For a real-server performance baseline, use synthetic SOC data and the active Rules Library:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/benchmark_performance.py \
  --sizes-mb 100 500
```

If healthy, continue with:

```bash
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/benchmark_performance.py \
  --sizes-mb 1024 2048
```

Review throughput, wall time, CPU, peak memory, report time, output time, replacement count, and errors. See `PERFORMANCE_BENCHMARK.md` for methodology.

## 23. Application release / deployment change control

For production or air-gapped deployment:

- use the OS/Python/architecture-specific offline artifact;
- do not use `--online` in production;
- verify bundled wheel checksums;
- allow deployment to rebuild `.venv`;
- run environment verification;
- confirm systemd and `/healthz`;
- run Admin and Analyst acceptance checks;
- run a representative sanitization job before go-live.

Production expected paths include:

```text
Application:   /opt/sanitization-app
Service user:  sanitizer
Environment:   /etc/sanitization-app/sanitization.env
Service:       sanitization-app.service
HTTPS port:    8443
Job database:  /opt/sanitization-app/data/jobs.db
Rules file:    /opt/sanitization-app/bad_words.txt
App logs:      /opt/sanitization-app/logs/
```

## 24. Ubuntu upgrade procedure

**Never reuse the application's old virtual environment across an Ubuntu release upgrade.**

Procedure:

1. Back up application state, Rules Library, approved configuration, and TLS material according to local policy.
2. Stop `sanitization-app`.
3. Upgrade Ubuntu.
4. Record the new OS and `python3 --version`.
5. Do not start the old `.venv` as the production runtime.
6. Deploy the offline release built and tested for the new Ubuntu/Python/architecture target.
7. Allow deployment to rebuild `.venv` from the local wheelhouse.
8. Run `scripts/verify_environment.py`.
9. Validate `/healthz`, `/health`, and `/system-info`.
10. Run Admin and Analyst staging acceptance.
11. Run representative sanitization and performance checks as required.
12. Return the service to users only after successful acceptance.

See `OS_COMPATIBILITY_REVIEW.md` and `DEPLOYMENT.md` for detailed upgrade evidence and rollback guidance.

## 25. Production acceptance checklist

Before declaring a new deployment/upgrade operational, confirm:

- [ ] Correct Ubuntu/Python/architecture-specific release deployed
- [ ] Environment verifier reports `RESULT: PASSED`
- [ ] systemd service healthy
- [ ] `/healthz` returns `{"status":"ok"}`
- [ ] Dashboard shows correct host/runtime details
- [ ] Administrator login works
- [ ] Analyst login works
- [ ] Analyst cannot access Admin-only controls/endpoints
- [ ] Choose Files works
- [ ] Choose Folder works
- [ ] Drag-and-drop works
- [ ] Clear Selection works
- [ ] Start Sanitization works
- [ ] Direct single-file output works
- [ ] Folder/multi-file ZIP output works
- [ ] Excel audit report downloads correctly
- [ ] Reports/History search and refresh work
- [ ] Rules Library actions work for Admin
- [ ] User Management actions work for Admin
- [ ] Application Logs refresh works for Admin
- [ ] Unsupported/scanned/image-only content fails closed
- [ ] Representative version strings are not incorrectly masked when clearly in version context
- [ ] Real IPv4 examples are sanitized
- [ ] No unexpected application/service errors present
- [ ] Performance is acceptable for the target server

## 26. Escalation criteria

Escalate to the Administrator/DevOps/security owner when:

- a sensitive value remains visible in sanitized output;
- an excessive false-positive pattern materially damages operational content;
- the same supported file repeatedly fails;
- application health or runtime information is inconsistent;
- disk utilization threatens processing capacity;
- the Rules Library becomes unavailable or invalid;
- the service fails after an OS/application upgrade;
- authentication or authorization behaves unexpectedly;
- a suspected security incident involves the application or its host.

Stop sharing affected output until the issue is resolved and the affected data is reprocessed/validated.

## 27. Quick-reference commands

```bash
# Environment verification
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/scripts/verify_environment.py

# Service status
sudo systemctl status sanitization-app --no-pager

# Recent service logs
sudo journalctl -u sanitization-app -n 200 --no-pager

# Follow service logs
sudo journalctl -u sanitization-app -f

# List configured local users
sudo -u sanitizer /opt/sanitization-app/.venv/bin/python \
  /opt/sanitization-app/main.py --list-users

# Validate Gunicorn configuration
/opt/sanitization-app/.venv/bin/gunicorn \
  --check-config \
  --config /opt/sanitization-app/gunicorn.conf.py \
  wsgi:application
```

## 28. Related documents

- `README.md` - product overview and DevOps handoff
- `DEPLOYMENT.md` - deployment, TLS, service, health, logging, staging acceptance, rollback
- `OS_COMPATIBILITY_REVIEW.md` - Ubuntu compatibility investigation and upgrade procedure
- `PERFORMANCE_BENCHMARK.md` - benchmark methodology
- `requirements-lock.txt` - complete locked Python dependency chain

## 29. Revision history

| Version | Date | Description | Author |
|---|---|---|---|
| 1.0 | 09 Sep 2026 | Initial operational SOP for Log Sanitization Application v2.1 | Andy |

---

**End of SOP**
