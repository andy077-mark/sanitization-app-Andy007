"""Offline OCR helpers and raster-image sanitization.

The application never calls a cloud OCR service. OCR is performed by a local
Tesseract executable supplied by the host or an approved local tools directory.
Recognized sensitive text is permanently overwritten in raster pixels.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

ClassifyRule = Callable[[str, int], str]
AuditAdd = Callable[[dict, str, str, int, str, str], None]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
BASE = Path(__file__).resolve().parent.parent
OCR_TOOLS = BASE / "tools" / "ocr"


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


OCR_TIMEOUT_SECONDS = _env_int("SANIT_OCR_TIMEOUT_SECONDS", 120, 10, 1800)
OCR_DPI = _env_int("SANIT_OCR_DPI", 200, 100, 600)
OCR_PSM = _env_int("SANIT_OCR_PSM", 6, 3, 13)
OCR_MIN_CONFIDENCE = float(os.environ.get("SANIT_OCR_MIN_CONFIDENCE", "0") or 0)
OCR_LANG = os.environ.get("SANIT_OCR_LANG", "eng").strip() or "eng"
MAX_IMAGE_PIXELS = _env_int("SANIT_MAX_IMAGE_PIXELS", 120_000_000, 1_000_000, 500_000_000)


def find_tesseract() -> Path | None:
    """Locate an approved local Tesseract executable without downloading anything."""
    configured = os.environ.get("SANIT_TESSERACT_BINARY", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None

    if OCR_TOOLS.exists():
        for name in ("tesseract", "tesseract.exe"):
            for candidate in OCR_TOOLS.rglob(name):
                if candidate.is_file():
                    try:
                        candidate.chmod(candidate.stat().st_mode | 0o111)
                    except OSError:
                        pass
                    return candidate

    found = shutil.which("tesseract")
    return Path(found) if found else None


def ocr_engine_version() -> str | None:
    exe = find_tesseract()
    if not exe:
        return None
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    first = (result.stdout or result.stderr or "").splitlines()
    return first[0].strip() if first else str(exe)


def _tesseract_env() -> dict[str, str]:
    env = os.environ.copy()
    tessdata = os.environ.get("SANIT_TESSDATA_DIR", "").strip()
    if tessdata:
        env["TESSDATA_PREFIX"] = tessdata
    return env


def _run_tesseract_tsv(image) -> list[dict]:
    """Run local Tesseract and return recognized words with pixel bounding boxes."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    exe = find_tesseract()
    if not exe:
        raise ValueError(
            "OCR engine unavailable. Install an approved local Tesseract package or set "
            "SANIT_TESSERACT_BINARY to the local executable."
        )

    fd, temp_name = tempfile.mkstemp(prefix="sanit_ocr_", suffix=".png")
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        source = image
        if source.mode not in ("RGB", "L"):
            source = source.convert("RGB")
        source.save(temp_path, format="PNG")

        command = [
            str(exe),
            str(temp_path),
            "stdout",
            "-l",
            OCR_LANG,
            "--oem",
            "1",
            "--psm",
            str(OCR_PSM),
            "--dpi",
            str(OCR_DPI),
            "tsv",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=OCR_TIMEOUT_SECONDS,
            env=_tesseract_env(),
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Tesseract OCR failed").strip()
            raise ValueError(f"OCR failed: {detail[-1200:]}")

        words: list[dict] = []
        reader = csv.DictReader(io.StringIO(result.stdout), delimiter="\t")
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = float(row.get("conf") or -1)
                left = int(row.get("left") or 0)
                top = int(row.get("top") or 0)
                width = int(row.get("width") or 0)
                height = int(row.get("height") or 0)
            except (TypeError, ValueError):
                continue
            if confidence < OCR_MIN_CONFIDENCE or width <= 0 or height <= 0:
                continue
            line_key = (
                row.get("page_num") or "0",
                row.get("block_num") or "0",
                row.get("par_num") or "0",
                row.get("line_num") or "0",
            )
            words.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "bbox": (left, top, left + width, top + height),
                    "line": line_key,
                }
            )
        return words
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"OCR timed out after {OCR_TIMEOUT_SECONDS} seconds") from exc
    finally:
        temp_path.unlink(missing_ok=True)


def _build_ocr_text(words: list[dict]) -> tuple[str, list[dict]]:
    text = ""
    mapped: list[dict] = []
    previous_line = None
    for word in words:
        line_key = word["line"]
        if text:
            text += "\n" if previous_line is not None and line_key != previous_line else " "
        start = len(text)
        text += word["text"]
        end = len(text)
        item = dict(word)
        item["start"] = start
        item["end"] = end
        mapped.append(item)
        previous_line = line_key
    return text, mapped


def _collect_ranges(text: str, rules: list[str], classify_rule: ClassifyRule) -> list[tuple[int, int, str]]:
    """Mirror normal sequential X-masking while retaining OCR match ranges."""
    working = text
    ranges: list[tuple[int, int, str]] = []

    def apply(pattern: str, kind: str, flags: int = 0) -> None:
        nonlocal working

        def repl(match: re.Match[str]) -> str:
            ranges.append((match.start(), match.end(), kind))
            return "X" * len(match.group(0))

        working = re.sub(pattern, repl, working, flags=flags)

    apply(r"[^\x20-\x7E\n\r]", "Non-ASCII Character")
    for index, pattern in enumerate(rules, 1):
        apply(pattern, classify_rule(pattern, index), re.IGNORECASE)
    return ranges


def _union_bbox(items: list[dict]) -> tuple[int, int, int, int]:
    left = min(item["bbox"][0] for item in items)
    top = min(item["bbox"][1] for item in items)
    right = max(item["bbox"][2] for item in items)
    bottom = max(item["bbox"][3] for item in items)
    return left, top, right, bottom


def ocr_image_matches(image, rules: list[str], classify_rule: ClassifyRule) -> tuple[int, list[dict]]:
    """Return OCR word count and sensitive matches mapped to raster rectangles."""
    words = _run_tesseract_tsv(image)
    text, mapped = _build_ocr_text(words)
    if not text:
        return 0, []

    ranges = _collect_ranges(text, rules, classify_rule)
    matches: list[dict] = []
    for start, end, kind in ranges:
        selected = [item for item in mapped if item["start"] < end and item["end"] > start]
        if not selected:
            continue
        by_line: dict[tuple, list[dict]] = {}
        for item in selected:
            by_line.setdefault(item["line"], []).append(item)
        segments = []
        for line_items in by_line.values():
            segments.append(
                {
                    "bbox": _union_bbox(line_items),
                    "characters": max(1, sum(len(item["text"]) for item in line_items)),
                }
            )
        matches.append({"kind": kind, "segments": segments})
    return len(words), matches


def _redact_frame(image, matches: list[dict]):
    from PIL import ImageDraw, ImageFont

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    white = (255, 255, 255, 255) if image.mode == "RGBA" else (255, 255, 255)
    black = (0, 0, 0, 255) if image.mode == "RGBA" else (0, 0, 0)

    for match in matches:
        for segment in match["segments"]:
            left, top, right, bottom = segment["bbox"]
            pad = max(2, int(max(1, bottom - top) * 0.12))
            left = max(0, left - pad)
            top = max(0, top - pad)
            right = min(image.width, right + pad)
            bottom = min(image.height, bottom + pad)
            draw.rectangle((left, top, right, bottom), fill=white)
            # Pixel overwrite is the security boundary; X characters provide the
            # same visible masking convention used by text/document outputs.
            approx_chars = max(1, min(segment["characters"], max(1, (right - left) // 7)))
            draw.text((left + 2, top + 1), "X" * approx_chars, fill=black, font=font)
    return image


def _save_sanitized_frames(frames: list, destination: Path, suffix: str) -> None:
    suffix = suffix.lower()
    if not frames:
        raise ValueError("Image contains no readable frames")

    first = frames[0]
    if suffix in {".jpg", ".jpeg"}:
        first.convert("RGB").save(destination, format="JPEG", quality=95, optimize=True)
    elif suffix == ".png":
        first.save(destination, format="PNG", compress_level=6)
    elif suffix == ".bmp":
        first.convert("RGB").save(destination, format="BMP")
    elif suffix == ".webp":
        first.convert("RGB").save(destination, format="WEBP", quality=95, method=4)
    elif suffix in {".tif", ".tiff"}:
        converted = [frame.convert("RGB") for frame in frames]
        converted[0].save(
            destination,
            format="TIFF",
            save_all=True,
            append_images=converted[1:],
            compression="tiff_deflate",
        )
    else:
        raise ValueError(f"Unsupported OCR image type: {suffix or '(no extension)'}")


def sanitize_image_file(
    fpath: Path,
    rules: list[str],
    audit: dict,
    audit_name: str,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
    location_prefix: str = "Image OCR",
) -> int:
    """OCR and permanently mask sensitive text in a raster image.

    EXIF and other source metadata are intentionally not copied to the sanitized
    output. Multi-page TIFF is supported; animated WebP/GIF is not.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    fpath = Path(fpath)
    suffix = fpath.suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise ValueError(f"Unsupported OCR image type: {suffix or '(no extension)'}")

    tmp_out = fpath.with_suffix(fpath.suffix + ".sanit.tmp")
    total = 0
    try:
        with Image.open(fpath) as source:
            frame_count = int(getattr(source, "n_frames", 1) or 1)
            if frame_count > 1 and suffix not in {".tif", ".tiff"}:
                raise ValueError(
                    f"Animated/multi-frame {suffix} images are not supported; convert to a static image or TIFF"
                )

            frames = []
            for frame_index in range(frame_count):
                source.seek(frame_index)
                frame = ImageOps.exif_transpose(source.copy())
                if frame.mode not in ("RGB", "RGBA"):
                    frame = frame.convert("RGB")
                _, matches = ocr_image_matches(frame, rules, classify_rule)
                frame = _redact_frame(frame, matches)
                frames.append(frame)

                location = location_prefix
                if frame_count > 1:
                    location += f" frame {frame_index + 1}"
                for match in matches:
                    audit_add(audit, audit_name, match["kind"], 1, location, "")
                    total += 1

        _save_sanitized_frames(frames, tmp_out, suffix)
        with Image.open(tmp_out) as check:
            check.load()
        tmp_out.replace(fpath)
        return total
    except UnidentifiedImageError as exc:
        tmp_out.unlink(missing_ok=True)
        raise ValueError(f"Invalid or corrupt image file: {fpath.name}") from exc
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise


def sanitize_image_bytes(
    data: bytes,
    suffix: str,
    rules: list[str],
    audit: dict,
    audit_name: str,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
    location_prefix: str,
) -> tuple[bytes, int]:
    """Sanitize an embedded raster image and return replacement bytes."""
    suffix = suffix.lower()
    fd, temp_name = tempfile.mkstemp(prefix="sanit_embedded_", suffix=suffix)
    os.close(fd)
    path = Path(temp_name)
    try:
        path.write_bytes(data)
        total = sanitize_image_file(
            path,
            rules,
            audit,
            audit_name,
            classify_rule,
            audit_add,
            location_prefix=location_prefix,
        )
        return path.read_bytes(), total
    finally:
        path.unlink(missing_ok=True)
