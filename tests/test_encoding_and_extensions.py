import codecs

import pytest

from sanitization_v2.sanitize import sanitize_file_if_supported

RULES = ["TESTSECRET"]


def sanitize(path):
    audit = {}
    count = sanitize_file_if_supported(path, RULES, audit, path.name)
    return count, audit


def test_utf16le_bom_is_preserved_without_garbled_output(tmp_path):
    path = tmp_path / "windows-export.reg"
    original = "Windows Registry Editor Version 5.00\r\nUser=TESTSECRET\r\n"
    path.write_bytes(codecs.BOM_UTF16_LE + original.encode("utf-16-le"))

    count, _ = sanitize(path)
    data = path.read_bytes()

    assert count >= 1
    assert data.startswith(codecs.BOM_UTF16_LE)
    decoded = data[len(codecs.BOM_UTF16_LE):].decode("utf-16-le")
    assert "TESTSECRET" not in decoded
    assert "User=XXXXXXXXXX" in decoded


def test_utf16be_bom_is_preserved_without_garbled_output(tmp_path):
    path = tmp_path / "export.txt"
    original = "host=server01\nuser=TESTSECRET\n"
    path.write_bytes(codecs.BOM_UTF16_BE + original.encode("utf-16-be"))

    count, _ = sanitize(path)
    data = path.read_bytes()

    assert count >= 1
    assert data.startswith(codecs.BOM_UTF16_BE)
    decoded = data[len(codecs.BOM_UTF16_BE):].decode("utf-16-be")
    assert "TESTSECRET" not in decoded
    assert "user=XXXXXXXXXX" in decoded


def test_utf8_bom_is_preserved(tmp_path):
    path = tmp_path / "events.csv"
    path.write_bytes(codecs.BOM_UTF8 + b"user,event\r\nTESTSECRET,failed\r\n")

    sanitize(path)
    data = path.read_bytes()

    assert data.startswith(codecs.BOM_UTF8)
    decoded = data[len(codecs.BOM_UTF8):].decode("utf-8")
    assert "TESTSECRET" not in decoded
    assert "XXXXXXXXXX" in decoded


def test_windows_1252_text_is_preserved_as_windows_1252(tmp_path):
    path = tmp_path / "legacy.log"
    original = "caf\xe9 user=TESTSECRET\r\n".encode("latin1")
    path.write_bytes(original)

    sanitize(path)
    data = path.read_bytes()
    decoded = data.decode("cp1252")

    assert "TESTSECRET" not in decoded
    # Non-ASCII content is intentionally sanitized but the file remains valid cp1252.
    assert decoded.startswith("cafX user=XXXXXXXXXX")


@pytest.mark.parametrize(
    "filename",
    [
        "events.json",
        "events.ndjson",
        "config.yaml",
        "settings.ini",
        "application.conf",
        "script.ps1",
        "query.sql",
        "page.html",
        "notes.md",
        "service.service",
    ],
)
def test_extended_text_extensions_are_sanitized(tmp_path, filename):
    path = tmp_path / filename
    path.write_text("account=TESTSECRET\n", encoding="utf-8")

    count, _ = sanitize(path)

    assert count >= 1
    assert "TESTSECRET" not in path.read_text("utf-8")
    assert "XXXXXXXXXX" in path.read_text("utf-8")


def test_known_binary_pdf_fails_closed_instead_of_being_corrupted(tmp_path):
    path = tmp_path / "evidence.pdf"
    path.write_bytes(b"%PDF-1.7\nTESTSECRET\n" + bytes(range(32)))

    with pytest.raises(ValueError, match="Unsupported binary/document file type"):
        sanitize(path)
