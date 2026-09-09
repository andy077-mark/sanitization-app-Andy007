#!/usr/bin/env python3
"""Check an offline bundle/runtime manifest against the current Ubuntu host.

This script intentionally uses only the Python standard library so systemd can
run it before importing any application dependency. It provides a clear error
when an in-place OS/Python upgrade leaves an older application runtime behind.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


def os_release_values() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return values
    for raw in path.read_text("utf-8", errors="ignore").splitlines():
        if "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def main() -> int:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "RUNTIME_MANIFEST.json"
    if not manifest_path.is_file():
        # Development/online source checkouts do not necessarily have a release
        # manifest. The deployment verifier will still validate dependencies.
        print("Bundle manifest: not present (development/source deployment)")
        return 0

    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
    except Exception as exc:
        print(f"ERROR: invalid runtime manifest {manifest_path}: {exc}", file=sys.stderr)
        return 1

    os_values = os_release_values()
    actual = {
        "os_id": os_values.get("ID", "linux"),
        "os_version": os_values.get("VERSION_ID", "unknown"),
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "architecture": platform.machine(),
    }
    labels = {
        "os_id": "OS",
        "os_version": "Ubuntu version",
        "python_major_minor": "Python",
        "architecture": "architecture",
    }
    mismatches = []
    for key in labels:
        expected = str(manifest.get(key, "") or "")
        if expected and expected != str(actual[key]):
            mismatches.append(f"{labels[key]}: bundle={expected}, host={actual[key]}")

    if mismatches:
        print("ERROR: application release bundle does not match the current host:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  - {mismatch}", file=sys.stderr)
        print(
            "This commonly occurs after an in-place Ubuntu upgrade changes the system Python version.\n"
            "Deploy the offline release bundle built and tested for this Ubuntu/Python version; "
            "do not reuse the previous OS virtual environment.",
            file=sys.stderr,
        )
        return 1

    print(
        "Bundle compatibility: OK - "
        f"{actual['os_id']} {actual['os_version']} / Python {actual['python_major_minor']} / {actual['architecture']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
