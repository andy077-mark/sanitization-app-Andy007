"""Sanitization rule storage, validation, and reload helpers."""
from __future__ import annotations

import re

from . import config as cfg


def rules_path():
    return cfg.BASE / cfg.RULES_FILE


def read_rules_file() -> list[str]:
    path = rules_path()
    if not path.exists():
        return []
    return path.read_text("utf-8").splitlines()


def parse_active_patterns(lines: list[str]) -> list[str]:
    patterns = []
    for line in lines:
        clean = line.split("#", 1)[0].strip()
        if clean:
            patterns.append(clean)
    return patterns


def validate_patterns(patterns: list[str]):
    for i, pat in enumerate(patterns, start=1):
        try:
            re.compile(pat)
        except re.error as exc:
            return False, f"Line {i}: invalid regex — {exc}"
    return True, None


def validate_patterns_in_lines(lines: list[str]):
    for i, line in enumerate(lines, start=1):
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        try:
            re.compile(clean)
        except re.error as exc:
            return False, f"Line {i}: invalid regex — {exc}"
    return True, None


def write_rules_file(lines: list[str]) -> list[str]:
    global BAD_PATTERNS
    path = rules_path()
    tmp = path.with_suffix(".txt.tmp")
    content = "\n".join(lines)
    if lines:
        content += "\n"
    with cfg.rules_lock:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        BAD_PATTERNS = parse_active_patterns(lines)
    return BAD_PATTERNS


def load_bad_patterns() -> list[str]:
    return parse_active_patterns(read_rules_file())


def reload_bad_patterns() -> list[str]:
    global BAD_PATTERNS
    with cfg.rules_lock:
        BAD_PATTERNS = load_bad_patterns()
    return BAD_PATTERNS


BAD_PATTERNS = load_bad_patterns()
