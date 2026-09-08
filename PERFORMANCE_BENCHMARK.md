# SOC Data Sanitization Platform v2.1 - Performance Benchmark

This benchmark establishes a repeatable performance baseline on the actual Ubuntu staging/production-class server.

It uses **synthetic SOC-style log data only**. No real SOC evidence, credentials, IP inventory or production logs are required.

By default, the benchmark runs through the application's **currently active Rules Library**, so the results reflect the real regex/rule workload configured on that server.

## What is measured

For each test size, the benchmark records:

- Input size in MB
- Active rule count
- End-to-end sanitization wall-clock time
- Core processing time
- Excel report generation time
- Output preparation time
- End-to-end throughput in MB/s
- Core processing throughput in MB/s
- CPU seconds
- Approximate process CPU utilization
- Peak process memory / RSS
- Total replacements
- Output type and output size
- Success/failure status and error if applicable

Synthetic file-generation time is measured separately and is **not** included in the sanitization throughput figure.

## Default test sizes

```text
100 MB
500 MB
1024 MB (1 GB)
2048 MB (2 GB)
```

The 2 GB test should only be run when the staging server has adequate free disk space. The script performs a free-space safety check before starting.

## Recommended execution conditions

For the most meaningful baseline:

1. Run on the actual Ubuntu staging host intended to represent production.
2. Stop unrelated heavy CPU/disk jobs if operationally safe.
3. Use the same Rules Library intended for production.
4. Run the benchmark at least twice and compare results.
5. Record the VM/server CPU, RAM and storage type with the result.
6. Do not run the 2 GB test when the host is low on disk.

The benchmark does not require the web service to be stopped. However, for the cleanest single-job baseline, run it during a quiet staging window.

## Run the complete benchmark

From the application directory:

```bash
cd /opt/sanitization-app
sudo -u sanitizer .venv/bin/python scripts/benchmark_performance.py
```

Default sizes are:

```text
100 500 1024 2048 MB
```

## Run a smaller first pass

Before the full benchmark, a useful first run is:

```bash
cd /opt/sanitization-app
sudo -u sanitizer .venv/bin/python scripts/benchmark_performance.py --sizes-mb 100 500
```

If that completes successfully and disk space is healthy, continue with:

```bash
sudo -u sanitizer .venv/bin/python scripts/benchmark_performance.py --sizes-mb 1024 2048
```

## Results

Results are saved by default under:

```text
/opt/sanitization-app/data/benchmarks/
```

Two files are produced per benchmark run:

```text
sanitization-benchmark-YYYYMMDD-HHMMSS.json
sanitization-benchmark-YYYYMMDD-HHMMSS.csv
```

The JSON includes server metadata and detailed results. The CSV is convenient for comparison, reporting and Excel analysis.

Example console summary:

```text
======================================================================
RESULTS
  Size MB     Wall s       MB/s   Proc MB/s    CPU %   Peak MB   Replacements
      100       4.82       20.75        22.10     96.4     184.0        14,220
      500      23.30       21.46        22.02     97.1     188.0        71,102
     1024      47.80       21.42        21.98     97.5     190.0       145,630
     2048      95.70       21.40        21.93     97.8     194.0       291,260
```

The numbers above are examples only. The real server results must come from the actual benchmark run.

## Throughput interpretation

The main number for SOC operations is:

```text
throughput_mb_s = input size MB / end-to-end sanitization wall-clock seconds
```

The benchmark also reports `processing_throughput_mb_s`, which focuses on the core processing stage and helps separate regex/sanitization cost from report/output overhead.

As a practical example, if a 1 GB log takes 50 seconds end to end:

```text
1024 MB / 50 s = 20.48 MB/s
```

This becomes the established baseline for that server and Rules Library.

## Comparing future releases

When v2.2 or later changes the sanitization engine, run the same benchmark sizes on the same server with the same Rules Library.

Compare:

```text
Wall seconds
MB/s
Processing MB/s
CPU utilization
Peak RSS
Report seconds
Output seconds
```

A performance optimization should not be accepted solely because MB/s increases. Sanitization correctness, audit accuracy and security tests must remain green.

## Disk-space behavior

Large text sanitization temporarily needs both the working file and a `.sanit.tmp` output during replacement. The benchmark therefore checks available disk before the largest requested run and keeps additional safety headroom.

By default, large sanitized benchmark outputs are deleted after each test size to avoid consuming the server disk unnecessarily. JSON/CSV result files are retained.

To keep the generated sanitized outputs for manual inspection:

```bash
sudo -u sanitizer .venv/bin/python scripts/benchmark_performance.py --keep-outputs
```

Use that option only when sufficient disk space is available.

## Alternate Rules Library

The normal benchmark should use the active Rules Library. To benchmark against a different approved rules file:

```bash
sudo -u sanitizer .venv/bin/python scripts/benchmark_performance.py \
  --rules-file /approved/path/bad_words.txt
```

## Low-disk override

The safety check can be overridden with:

```text
--force-low-disk
```

This should not be used on the SOC server unless the operator has manually confirmed there is enough working space and accepts the risk of disk exhaustion.

## Recommended SOC baseline record

For each production release, retain:

```text
Application version / commit
Server hostname or asset ID
Ubuntu version
Python version
CPU model and logical CPU count
RAM
Rules count
100 MB result
500 MB result
1 GB result
2 GB result (when approved)
Benchmark date/time
```

This provides a repeatable performance record for future tuning and change-management evidence.
