"""Safe text encoding detection and supported text-like extensions.

This module deliberately avoids heuristic third-party charset guessing. It
recognizes the encodings commonly encountered in SOC exports/configuration
files and refuses content that does not look safely textual.
"""
from __future__ import annotations

import codecs
from pathlib import Path

# Text-based formats that can safely use the normal line-oriented sanitizer.
# Binary/document container formats such as PDF/DOCX are intentionally excluded
# and require dedicated parsers before they can be supported safely.
TEXT_LIKE_EXTS = {
    ".txt", ".log", ".csv", ".tsv", ".json", ".jsonl", ".ndjson",
    ".xml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".config",
    ".properties", ".env", ".md", ".rst", ".html", ".htm", ".css",
    ".js", ".ts", ".py", ".ps1", ".psm1", ".psd1", ".sh", ".bash",
    ".zsh", ".bat", ".cmd", ".vbs", ".sql", ".reg", ".inf", ".service",
    ".socket", ".timer", ".rules", ".list", ".hosts",
}

# These formats must never be treated as plain text merely because their first
# bytes happen to be ASCII-readable. Dedicated format support can be added later.
KNOWN_BINARY_EXTS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".exe", ".dll", ".sys", ".bin", ".dat", ".evtx", ".evt", ".pcap",
    ".pcapng", ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb",
}

SAMPLE_BYTES = 64 * 1024


def _printable_ratio(text: str) -> float:
    if not text:
        return 1.0
    acceptable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return acceptable / len(text)


def _utf16_without_bom(sample: bytes) -> str | None:
    """Recognize common BOM-less UTF-16 ASCII-heavy logs conservatively."""
    if len(sample) < 8:
        return None
    even = sample[0::2]
    odd = sample[1::2]
    if not even or not odd:
        return None
    even_zero = even.count(0) / len(even)
    odd_zero = odd.count(0) / len(odd)

    # ASCII-heavy UTF-16LE normally has NULs in the odd byte positions;
    # UTF-16BE has them in the even positions. Require a strong asymmetry so
    # arbitrary binary data is not guessed as text.
    if odd_zero >= 0.30 and even_zero <= 0.05:
        return "utf-16-le"
    if even_zero >= 0.30 and odd_zero <= 0.05:
        return "utf-16-be"
    return None


def detect_text_encoding(path: Path) -> tuple[str, bytes] | None:
    """Return ``(codec, BOM bytes)`` for safely recognized text, else None.

    Recognized encodings:
      * UTF-8
      * UTF-8 with BOM
      * UTF-16 LE / BE with BOM
      * conservative BOM-less UTF-16 LE / BE
      * Windows-1252 for high-printability legacy text
    """
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            sample = handle.read(SAMPLE_BYTES)
    except OSError:
        return None

    if not sample:
        return "utf-8", b""

    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8", codecs.BOM_UTF8
    if sample.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le", codecs.BOM_UTF16_LE
    if sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be", codecs.BOM_UTF16_BE

    if b"\x00" in sample:
        utf16 = _utf16_without_bom(sample)
        if utf16:
            try:
                decoded = sample.decode(utf16, errors="strict")
            except UnicodeDecodeError:
                return None
            if _printable_ratio(decoded) >= 0.90:
                return utf16, b""
        return None

    try:
        decoded = sample.decode("utf-8", errors="strict")
        if _printable_ratio(decoded) >= 0.90:
            return "utf-8", b""
    except UnicodeDecodeError:
        pass

    try:
        decoded = sample.decode("cp1252", errors="strict")
        if _printable_ratio(decoded) >= 0.95:
            return "cp1252", b""
    except UnicodeDecodeError:
        pass

    return None


def is_known_binary_extension(path: Path) -> bool:
    return Path(path).suffix.lower() in KNOWN_BINARY_EXTS
