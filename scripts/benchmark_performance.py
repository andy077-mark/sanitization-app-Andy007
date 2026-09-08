#!/usr/bin/env python3
"""Real-server performance benchmark for SOC Data Sanitization Platform v2.1.

The benchmark generates synthetic SOC-style text logs locally, processes them
through the same sanitization job engine used by the application, and writes
JSON/CSV results. Synthetic generation time is measured separately and is not
included in sanitization throughput.

By default the benchmark uses the server's currently active Rules Library so
results reflect the real production sanitization workload.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import resource
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sanitization_v2 import config as cfg  # noqa: E402
from sanitization_v2 import rules as rules_module  # noqa: E402
from sanitization_v2.jobs import process_file  # noqa: E402

DEFAULT_SIZES_MB = [100, 500, 1024, 2048]
SYNTHETIC_LINE = (
    "2026-09-08T10:25:31Z host=SRV-AD-01 user=andy "
    "src_ip=10.15.22.18 dest_ip=172.20.5.10 "
    "email=andy@company.com domain=company.com platform=Windows "
    'service="Active Directory" location="Abu Dhabi" tier=T2 '
    'event="authentication failed" message="synthetic benchmark 2023 csv"\n'
).encode("utf-8")


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def read_mem_total_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text("utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text("utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def system_snapshot() -> dict:
    usage = shutil.disk_usage(cfg.BASE)
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": cpu_model(),
        "logical_cpus": os.cpu_count(),
        "memory_total_mb": read_mem_total_mb(),
        "disk_free_gb": round(usage.free / (1024**3), 2),
        "app_root": str(cfg.BASE),
    }


def write_synthetic_log(path: Path, target_mb: int) -> tuple[int, float]:
    """Create an exact-ish target-size synthetic log without loading it in RAM."""
    target_bytes = int(target_mb) * 1024 * 1024
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    block = SYNTHETIC_LINE * max(1, (1024 * 1024) // len(SYNTHETIC_LINE))
    written = 0
    with open(path, "wb", buffering=1024 * 1024) as handle:
        while written + len(block) <= target_bytes:
            handle.write(block)
            written += len(block)
        remaining = target_bytes - written
        if remaining:
            repeats = (remaining // len(SYNTHETIC_LINE)) + 1
            handle.write((SYNTHETIC_LINE * repeats)[:remaining])
            written += remaining
        handle.flush()
        os.fsync(handle.fileno())
    return written, time.perf_counter() - started


def parse_performance_log(job_id: str) -> dict:
    path = cfg.LOGS / f"{job_id}.log"
    try:
        payload = json.loads(path.read_text("utf-8").splitlines()[-1])
        return payload.get("performance") or {}
    except (OSError, ValueError, IndexError, json.JSONDecodeError):
        return {}


def cleanup_job_files(info: dict, job_id: str, source: Path, keep_outputs: bool) -> None:
    source.unlink(missing_ok=True)
    if not keep_outputs:
        for key in ("output_path", "report_path"):
            raw = info.get(key)
            if not raw:
                continue
            path = Path(raw)
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                    # Direct single-file output is stored under outputs/<job_id>/.
                    parent = path.parent
                    if parent.name == job_id and parent.exists():
                        shutil.rmtree(parent, ignore_errors=True)
            except OSError:
                pass
    cfg.SESSIONS.pop(job_id, None)


def run_one(size_mb: int, active_rules: list[str], keep_outputs: bool) -> dict:
    job_id = "bench" + uuid.uuid4().hex[:8]
    filename = f"benchmark_{size_mb}MB.log"
    source = cfg.UPLOAD / f"{job_id}_00000_{filename}"

    print(f"\n[{size_mb} MB] Generating synthetic log...", flush=True)
    actual_bytes, generation_seconds = write_synthetic_log(source, size_mb)
    actual_mb = actual_bytes / (1024 * 1024)

    token = cfg.new_job_token()
    cfg.SESSIONS[job_id] = {
        "status": "Queued",
        "progress": 0,
        "token": token,
        "time": datetime.now(),
        "filenames": [filename],
        "created_by": "BENCHMARK",
    }
    cfg.db_create_job(job_id, [filename], "BENCHMARK", token, created_by="BENCHMARK")

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    cpu_before = time.process_time()
    wall_started = time.perf_counter()
    process_file(job_id, [source], [filename], [filename], "BENCHMARK", active_rules)
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_before
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    info = dict(cfg.SESSIONS.get(job_id) or {})
    perf = parse_performance_log(job_id)
    row = {
        "size_mb": round(actual_mb, 2),
        "rules": len(active_rules),
        "status": info.get("status", "Unknown"),
        "generation_seconds": round(generation_seconds, 3),
        "wall_seconds": round(wall_seconds, 3),
        "processing_seconds": float(perf.get("processing_seconds", 0) or 0),
        "report_seconds": float(perf.get("report_seconds", 0) or 0),
        "output_seconds": float(
            perf.get("output_seconds", perf.get("packaging_seconds", 0)) or 0
        ),
        "throughput_mb_s": round(actual_mb / wall_seconds, 2) if wall_seconds else 0,
        "processing_throughput_mb_s": round(
            actual_mb / float(perf.get("processing_seconds", 0)), 2
        ) if float(perf.get("processing_seconds", 0) or 0) > 0 else 0,
        "cpu_seconds": round(cpu_seconds, 3),
        "approx_cpu_util_pct": round((cpu_seconds / wall_seconds) * 100, 1) if wall_seconds else 0,
        "peak_rss_mb": round(rss_after / 1024, 1),
        "peak_rss_before_mb": round(rss_before / 1024, 1),
        "replacements": int(info.get("total_replacements", 0) or 0),
        "output_type": info.get("output_type", ""),
        "output_size_mb": 0,
        "error": info.get("error") or "",
        "job_id": job_id,
    }
    output_path = info.get("output_path")
    if output_path and Path(output_path).exists() and Path(output_path).is_file():
        row["output_size_mb"] = round(Path(output_path).stat().st_size / (1024 * 1024), 2)

    if row["status"] == "Done":
        print(
            f"[{size_mb} MB] Done in {row['wall_seconds']:.2f}s | "
            f"{row['throughput_mb_s']:.2f} MB/s end-to-end | "
            f"{row['processing_throughput_mb_s']:.2f} MB/s processing | "
            f"{row['replacements']:,} replacements",
            flush=True,
        )
    else:
        print(f"[{size_mb} MB] FAILED: {row['error']}", flush=True)

    cleanup_job_files(info, job_id, source, keep_outputs)
    return row


def write_results(rows: list[dict], metadata: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"sanitization-benchmark-{stamp}.json"
    csv_path = out_dir / f"sanitization-benchmark-{stamp}.csv"
    json_path.write_text(
        json.dumps({"metadata": metadata, "results": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark sanitization throughput on the real application server"
    )
    parser.add_argument(
        "--sizes-mb",
        nargs="+",
        type=int,
        default=DEFAULT_SIZES_MB,
        help="Synthetic log sizes in MB (default: 100 500 1024 2048)",
    )
    parser.add_argument(
        "--rules-file",
        help="Optional alternate rules file. Default is the server's active Rules Library.",
    )
    parser.add_argument(
        "--keep-outputs",
        action="store_true",
        help="Keep generated sanitized outputs. Default deletes large benchmark outputs after each run.",
    )
    parser.add_argument(
        "--force-low-disk",
        action="store_true",
        help="Run even when free-space safety check is below the recommended threshold.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(cfg.DATA / "benchmarks"),
        help="Directory for JSON/CSV benchmark results.",
    )
    args = parser.parse_args()

    sizes = [value for value in args.sizes_mb if value > 0]
    if not sizes:
        parser.error("at least one positive --sizes-mb value is required")

    if args.rules_file:
        lines = Path(args.rules_file).read_text("utf-8").splitlines()
        active_rules = rules_module.parse_active_patterns(lines)
        rules_source = str(Path(args.rules_file).resolve())
    else:
        active_rules = rules_module.reload_bad_patterns()
        rules_source = str(cfg.RULES_FILE)

    snapshot = system_snapshot()
    largest_mb = max(sizes)
    free_bytes = shutil.disk_usage(cfg.BASE).free
    # Sanitizing a text file temporarily needs both original and .sanit.tmp;
    # allow extra headroom for output/report/runtime files.
    recommended_free = int((largest_mb * 3 + 2048) * 1024 * 1024)
    if free_bytes < recommended_free and not args.force_low_disk:
        print(
            "ERROR: insufficient free disk for safe benchmark execution.\n"
            f"Free: {human_bytes(free_bytes)}\n"
            f"Recommended for largest {largest_mb} MB run: {human_bytes(recommended_free)}\n"
            "Free space first, reduce --sizes-mb, or use --force-low-disk only if you accept the risk.",
            file=sys.stderr,
        )
        return 2

    print("SOC Data Sanitization Platform - Real Server Benchmark")
    print("=" * 70)
    print(f"Host:             {snapshot['hostname']}")
    print(f"Platform:         {snapshot['platform']}")
    print(f"Python:           {snapshot['python']}")
    print(f"CPU:              {snapshot['cpu_model']}")
    print(f"Logical CPUs:     {snapshot['logical_cpus']}")
    print(f"Memory:           {snapshot['memory_total_mb']} MB")
    print(f"Free disk:        {snapshot['disk_free_gb']} GB")
    print(f"Active rules:     {len(active_rules)}")
    print(f"Rules source:     {rules_source}")
    print(f"Sizes:            {', '.join(str(v) + ' MB' for v in sizes)}")
    print("Synthetic data:   yes (no real SOC data)")
    print("Generation time:  excluded from throughput")

    rows: list[dict] = []
    for size_mb in sizes:
        rows.append(run_one(size_mb, active_rules, args.keep_outputs))
        if rows[-1]["status"] != "Done":
            print("Stopping after failed benchmark size.", file=sys.stderr)
            break

    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "system": snapshot,
        "rules_source": rules_source,
        "active_rule_count": len(active_rules),
        "sizes_requested_mb": sizes,
        "keep_outputs": bool(args.keep_outputs),
        "throughput_definition": "input MB / process_file wall-clock seconds; synthetic generation excluded",
    }
    json_path, csv_path = write_results(rows, metadata, Path(args.output_dir))

    print("\n" + "=" * 70)
    print("RESULTS")
    print(f"{'Size MB':>9} {'Wall s':>10} {'MB/s':>10} {'Proc MB/s':>11} {'CPU %':>8} {'Peak MB':>9} {'Replacements':>14}")
    for row in rows:
        print(
            f"{row['size_mb']:>9.0f} {row['wall_seconds']:>10.2f} "
            f"{row['throughput_mb_s']:>10.2f} {row['processing_throughput_mb_s']:>11.2f} "
            f"{row['approx_cpu_util_pct']:>8.1f} {row['peak_rss_mb']:>9.1f} "
            f"{row['replacements']:>14,}"
        )
    print(f"\nJSON: {json_path}")
    print(f"CSV:  {csv_path}")
    if any(row["status"] != "Done" for row in rows):
        print("RESULT: FAILED")
        return 1
    print("RESULT: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
