#!/usr/bin/env python3
"""Pre-deployment verification for SOC Data Sanitization Platform v2."""
from __future__ import annotations

import importlib.metadata as metadata
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path

EXPECTED = {
    "Flask": "3.1.3",
    "cryptography": "50.0.1",
    "openpyxl": "3.1.5",
    "xlrd": "2.0.2",
    "xlwt": "1.3.0",
}


def os_release() -> str:
    path = Path("/etc/os-release")
    if not path.exists():
        return platform.platform()
    values = {}
    for line in path.read_text("utf-8", errors="ignore").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return f"{values.get('NAME', platform.system())} {values.get('VERSION_ID', '')}".strip()


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    print("SOC Data Sanitization Platform v2 - Environment Check")
    print("=" * 62)
    print(f"OS:       {os_release()}")
    print(f"Platform: {platform.machine()} / {platform.system()}")
    print(f"Python:   {platform.python_version()}")

    if sys.version_info < (3, 10):
        failures.append("Python 3.10 or newer is required")

    for package, expected in EXPECTED.items():
        try:
            actual = metadata.version(package)
            marker = "OK" if actual == expected else "MISMATCH"
            print(f"{package:<14} {actual:<12} {marker}")
            if actual != expected:
                failures.append(f"{package} must be {expected}; found {actual}")
        except metadata.PackageNotFoundError:
            failures.append(f"Missing Python package: {package}=={expected}")

    try:
        from sanitization_v2 import config as cfg

        for name in ("UPLOAD", "OUTPUT", "LOGS", "TEMP", "DATA"):
            path = getattr(cfg, name)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            print(f"Writable:  {name:<8} {path}")

        template = cfg.BASE / "templates" / "index.html"
        if not template.is_file():
            failures.append(f"Missing UI template: {template}")

        rules = cfg.BASE / "bad_words.txt"
        if not rules.is_file():
            failures.append(f"Missing rules file: {rules}")

        cfg.init_db()
        with sqlite3.connect(cfg.DB_PATH) as connection:
            connection.execute("SELECT 1").fetchone()
        print(f"SQLite:    OK ({cfg.DB_PATH})")

        cfg.ensure_selfsigned_certs()
        cert = cfg.BASE / "certs" / "cert.pem"
        key = cfg.BASE / "certs" / "key.pem"
        if not cert.exists() or not key.exists():
            failures.append("TLS certificate/key could not be created")
        else:
            print("TLS:       certificate/key ready")

        seven_zip = cfg.ensure_7zip(False)
        if seven_zip:
            print(f"7-Zip:     OK ({seven_zip})")
        else:
            warnings.append("7-Zip not found: ZIP/TAR/GZ/BZ2/XZ work, but RAR/7Z require a local 7-Zip binary")

        free_gb = shutil.disk_usage(cfg.BASE).free / (1024 ** 3)
        print(f"Disk free: {free_gb:.1f} GB")
        if free_gb < 5:
            warnings.append("Less than 5 GB free disk space; large archive processing may fail")
    except Exception as exc:
        failures.append(f"Application environment check failed: {exc}")

    print("-" * 62)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print("RESULT: FAILED")
        return 1
    print("RESULT: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
