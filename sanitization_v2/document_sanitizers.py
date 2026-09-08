"""Dedicated sanitizers for structured document formats.

PDF sanitization uses true PDF redaction for extractable text and local OCR for
raster/scanned regions. DOCX sanitization updates text-bearing XML nodes and OCR-
sanities embedded raster images while preserving the Office package structure.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Callable

from .ocr_sanitizer import IMAGE_EXTS, OCR_DPI, ocr_image_matches, sanitize_image_bytes

SanitizeContent = Callable[[str, list[str] | None], tuple[str, int, dict[str, int]]]
ClassifyRule = Callable[[str, int], str]
AuditAdd = Callable[[dict, str, str, int, str, str], None]


def _collect_sanitize_ranges(
    text: str,
    rules: list[str],
    classify_rule: ClassifyRule,
) -> tuple[str, list[tuple[int, int, str]]]:
    """Apply normal sequential X-masking semantics and retain stable match ranges."""
    working = text
    ranges: list[tuple[int, int, str]] = []

    def apply_pattern(pattern: str, kind: str, flags: int = 0) -> None:
        nonlocal working

        def replace(match: re.Match[str]) -> str:
            ranges.append((match.start(), match.end(), kind))
            return "X" * len(match.group(0))

        working = re.sub(pattern, replace, working, flags=flags)

    apply_pattern(r"[^\x20-\x7E\n\r]", "Non-ASCII Character")
    for idx, pattern in enumerate(rules, 1):
        apply_pattern(pattern, classify_rule(pattern, idx), re.IGNORECASE)
    return working, ranges


def _rect_union(fitz, boxes: list[tuple[float, float, float, float]]):
    rect = fitz.Rect(boxes[0])
    for box in boxes[1:]:
        rect.include_rect(fitz.Rect(box))
    return rect


def _pdf_page_character_map(page) -> tuple[str, list[dict]]:
    """Build text and per-character rectangles from PyMuPDF raw text extraction."""
    raw = page.get_text("rawdict")
    chars: list[dict] = []
    line_id = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for item in span.get("chars", []):
                    value = str(item.get("c", ""))
                    bbox = tuple(item.get("bbox", (0, 0, 0, 0)))
                    for ch in value:
                        chars.append({"char": ch, "bbox": bbox, "line": line_id})
            chars.append({"char": "\n", "bbox": None, "line": line_id})
            line_id += 1
    return "".join(item["char"] for item in chars), chars


def _add_native_pdf_redactions(
    page,
    page_index: int,
    rules: list[str],
    audit: dict,
    audit_name: str,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
):
    import pymupdf as fitz

    text, char_map = _pdf_page_character_map(page)
    _, ranges = _collect_sanitize_ranges(text, rules, classify_rule)
    redactions: list[tuple[object, str]] = []
    total = 0

    for start, end, kind in ranges:
        segment = char_map[start:end]
        by_line: dict[int, list[dict]] = {}
        for item in segment:
            if item["bbox"] is None:
                continue
            by_line.setdefault(int(item["line"]), []).append(item)
        if not by_line:
            raise ValueError(
                f"PDF sanitization could not safely map a match to page coordinates on page {page_index}"
            )
        for line_items in by_line.values():
            boxes = [item["bbox"] for item in line_items if item["bbox"] is not None]
            rect = _rect_union(fitz, boxes)
            redactions.append((rect, "X" * max(1, len(line_items))))
        audit_add(audit, audit_name, kind, 1, f"Page {page_index}", "")
        total += 1
    return redactions, total


def _page_image_regions(page):
    """Return unique raster-image rectangles on a PDF page, including inline images."""
    import pymupdf as fitz

    regions = []
    seen: set[tuple[float, float, float, float]] = set()
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        infos = []
    for info in infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        rect = fitz.Rect(bbox)
        if rect.is_empty or rect.width <= 1 or rect.height <= 1:
            continue
        key = tuple(round(value, 3) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
        if key in seen:
            continue
        seen.add(key)
        regions.append(rect)
    return regions


def _add_ocr_pdf_redactions(
    page,
    page_index: int,
    rules: list[str],
    audit: dict,
    audit_name: str,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
):
    """OCR only raster-image regions so native PDF text is not double-counted."""
    import pymupdf as fitz
    from PIL import Image

    redactions: list[tuple[object, str]] = []
    total = 0
    inspected = 0

    for image_index, clip in enumerate(_page_image_regions(page), 1):
        pix = page.get_pixmap(dpi=OCR_DPI, clip=clip, alpha=False)
        if pix.width <= 0 or pix.height <= 0:
            continue
        raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        _, matches = ocr_image_matches(raster, rules, classify_rule)
        inspected += 1
        scale_x = clip.width / pix.width
        scale_y = clip.height / pix.height

        for match in matches:
            for segment in match["segments"]:
                left, top, right, bottom = segment["bbox"]
                mapped = fitz.Rect(
                    clip.x0 + left * scale_x,
                    clip.y0 + top * scale_y,
                    clip.x0 + right * scale_x,
                    clip.y0 + bottom * scale_y,
                )
                # Small padding covers anti-aliased glyph edges in raster scans.
                pad_x = min(1.5, max(0.4, mapped.height * 0.08))
                pad_y = min(1.5, max(0.4, mapped.height * 0.08))
                mapped.x0 = max(clip.x0, mapped.x0 - pad_x)
                mapped.y0 = max(clip.y0, mapped.y0 - pad_y)
                mapped.x1 = min(clip.x1, mapped.x1 + pad_x)
                mapped.y1 = min(clip.y1, mapped.y1 + pad_y)
                overlay = "X" * max(1, min(int(segment["characters"]), 40))
                redactions.append((mapped, overlay))
            audit_add(
                audit,
                audit_name,
                match["kind"],
                1,
                f"Page {page_index} image {image_index} OCR",
                "",
            )
            total += 1
    return redactions, total, inspected


def sanitize_pdf_file(
    fpath: Path,
    rules: list[str],
    audit: dict,
    audit_name: str,
    sanitize_content: SanitizeContent,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
) -> int:
    """Sanitize PDF text and raster/scanned content with permanent redactions.

    Extractable text is mapped directly to PDF coordinates. Raster regions are
    rendered locally and inspected with Tesseract OCR. Password-protected PDFs
    and PDFs with embedded files fail closed.
    """
    import pymupdf as fitz

    fpath = Path(fpath)
    tmp_out = fpath.with_suffix(fpath.suffix + ".sanit.tmp")
    total = 0
    doc = fitz.open(fpath)
    try:
        if doc.needs_pass:
            raise ValueError(f"Password-protected PDF is not supported: {fpath.name}")
        try:
            embedded_count = doc.embfile_count()
        except Exception:
            embedded_count = 0
        if embedded_count:
            raise ValueError(
                f"PDF contains {embedded_count} embedded file(s); embedded content must be sanitized separately"
            )

        for page_index, page in enumerate(doc, 1):
            native_redactions, native_total = _add_native_pdf_redactions(
                page,
                page_index,
                rules,
                audit,
                audit_name,
                classify_rule,
                audit_add,
            )
            ocr_redactions, ocr_total, _ = _add_ocr_pdf_redactions(
                page,
                page_index,
                rules,
                audit,
                audit_name,
                classify_rule,
                audit_add,
            )
            total += native_total + ocr_total
            all_redactions = native_redactions + ocr_redactions
            if not all_redactions:
                continue

            for rect, overlay in all_redactions:
                font_size = max(5.0, min(11.0, float(rect.height) * 0.72))
                page.add_redact_annot(
                    rect,
                    text=overlay,
                    fontname="helv",
                    fontsize=font_size,
                    fill=(1, 1, 1),
                    text_color=(0, 0, 0),
                    cross_out=False,
                )
            # OCR redactions must overwrite the underlying image pixels. Native-
            # only redactions preserve raster artwork outside the redaction area.
            page.apply_redactions(images=2 if ocr_redactions else 0, graphics=0, text=0)

        metadata = dict(doc.metadata or {})
        changed_metadata = False
        for key, value in list(metadata.items()):
            if not isinstance(value, str) or not value:
                continue
            sanitized, count, counts = sanitize_content(value, rules)
            if count:
                metadata[key] = sanitized
                changed_metadata = True
                total += count
                for kind, kind_count in counts.items():
                    audit_add(audit, audit_name, kind, kind_count, f"PDF metadata: {key}", "")
        if changed_metadata:
            doc.set_metadata(metadata)

        doc.save(tmp_out, garbage=4, clean=True, deflate=True)
    finally:
        doc.close()

    try:
        with fitz.open(tmp_out) as check:
            if check.needs_pass:
                raise ValueError("Sanitized PDF unexpectedly requires a password")
            for page in check:
                page.get_text("text")
        tmp_out.replace(fpath)
        return total
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _docx_part_label(name: str) -> str:
    base = Path(name).name
    if name == "word/document.xml":
        return "Document"
    if base.startswith("header"):
        return base.replace(".xml", "").replace("header", "Header ")
    if base.startswith("footer"):
        return base.replace(".xml", "").replace("footer", "Footer ")
    if base == "footnotes.xml":
        return "Footnotes"
    if base == "endnotes.xml":
        return "Endnotes"
    if base == "comments.xml":
        return "Comments"
    return base


def _distribute_same_length_text(nodes: list, sanitized: str) -> None:
    offset = 0
    for node in nodes:
        original = node.text or ""
        length = len(original)
        node.text = sanitized[offset : offset + length]
        offset += length
    if offset != len(sanitized):
        raise ValueError("DOCX sanitizer length invariant failed")


def _process_word_xml_part(
    data: bytes,
    part_name: str,
    rules: list[str],
    audit: dict,
    audit_name: str,
    sanitize_content: SanitizeContent,
    audit_add: AuditAdd,
) -> tuple[bytes, int, int]:
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(data, parser=parser)
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p_tag = f"{{{w_ns}}}p"
    text_tags = {
        f"{{{w_ns}}}t",
        f"{{{w_ns}}}instrText",
        f"{{{w_ns}}}delText",
        f"{{{w_ns}}}delInstrText",
    }
    total = 0
    paragraph_count = 0
    label = _docx_part_label(part_name)

    for paragraph in root.iter(p_tag):
        nodes = []
        for node in paragraph.iter():
            if node.tag not in text_tags:
                continue
            nearest_paragraph = next((ancestor for ancestor in node.iterancestors(p_tag)), None)
            if nearest_paragraph is paragraph:
                nodes.append(node)
        if not nodes:
            continue
        paragraph_count += 1
        original = "".join(node.text or "" for node in nodes)
        if not original:
            continue
        sanitized, count, counts = sanitize_content(original, rules)
        if not count:
            continue
        if len(sanitized) != len(original):
            raise ValueError("DOCX sanitizer must preserve text length")
        _distribute_same_length_text(nodes, sanitized)
        total += count
        for kind, kind_count in counts.items():
            audit_add(
                audit,
                audit_name,
                kind,
                kind_count,
                f"{label} paragraph {paragraph_count}",
                "",
            )

    # Drawing alt-text can also contain hostnames, case names or other sensitive
    # identifiers even when it is not visible on the page.
    for element in root.iter():
        for attr_name, value in list(element.attrib.items()):
            local = _xml_local_name(attr_name)
            if local not in {"descr", "title"} or not value:
                continue
            sanitized, count, counts = sanitize_content(value, rules)
            if not count:
                continue
            element.set(attr_name, sanitized)
            total += count
            for kind, kind_count in counts.items():
                audit_add(audit, audit_name, kind, kind_count, f"{label} image alt text", "")

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None), total, paragraph_count


def _process_metadata_xml(
    data: bytes,
    part_name: str,
    rules: list[str],
    audit: dict,
    audit_name: str,
    sanitize_content: SanitizeContent,
    audit_add: AuditAdd,
) -> tuple[bytes, int]:
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(data, parser=parser)
    total = 0
    for element in root.iter():
        if len(element) or not element.text:
            continue
        sanitized, count, counts = sanitize_content(element.text, rules)
        if not count:
            continue
        element.text = sanitized
        total += count
        for kind, kind_count in counts.items():
            audit_add(
                audit,
                audit_name,
                kind,
                kind_count,
                f"DOCX metadata: {_xml_local_name(element.tag)}",
                "",
            )
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None), total


def _process_relationships(
    data: bytes,
    part_name: str,
    rules: list[str],
    audit: dict,
    audit_name: str,
    sanitize_content: SanitizeContent,
    audit_add: AuditAdd,
) -> tuple[bytes, int]:
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    root = etree.fromstring(data, parser=parser)
    total = 0
    for relationship in root:
        if relationship.get("TargetMode") != "External":
            continue
        target = relationship.get("Target") or ""
        sanitized, count, counts = sanitize_content(target, rules)
        if not count:
            continue
        relationship.set("Target", sanitized)
        total += count
        for kind, kind_count in counts.items():
            audit_add(audit, audit_name, kind, kind_count, "DOCX external relationship", "")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=None), total


def sanitize_docx_file(
    fpath: Path,
    rules: list[str],
    audit: dict,
    audit_name: str,
    sanitize_content: SanitizeContent,
    classify_rule: ClassifyRule,
    audit_add: AuditAdd,
) -> int:
    """Sanitize DOCX text, metadata and embedded raster images with local OCR.

    Embedded OLE/files and macro payloads still fail closed. Supported raster
    images under word/media are OCR-sanitized and have their image metadata
    stripped before being written back to the DOCX package.
    """
    from docx import Document

    fpath = Path(fpath)
    tmp_out = fpath.with_suffix(fpath.suffix + ".sanit.tmp")
    total = 0

    try:
        with zipfile.ZipFile(fpath, "r") as src:
            names = src.namelist()
            if any(name.startswith("word/embeddings/") for name in names):
                raise ValueError("DOCX contains embedded/OLE files; embedded content must be sanitized separately")
            if any(name.endswith("vbaProject.bin") for name in names):
                raise ValueError("Macro-enabled Word content is not supported by the DOCX sanitizer")

            with zipfile.ZipFile(tmp_out, "w", compression=zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    data = src.read(info.filename)
                    name = info.filename
                    if name.startswith("word/") and name.endswith(".xml"):
                        data, count, _ = _process_word_xml_part(
                            data,
                            name,
                            rules,
                            audit,
                            audit_name,
                            sanitize_content,
                            audit_add,
                        )
                        total += count
                    elif name in {"docProps/core.xml", "docProps/custom.xml"}:
                        data, count = _process_metadata_xml(
                            data,
                            name,
                            rules,
                            audit,
                            audit_name,
                            sanitize_content,
                            audit_add,
                        )
                        total += count
                    elif name.startswith("word/_rels/") and name.endswith(".rels"):
                        data, count = _process_relationships(
                            data,
                            name,
                            rules,
                            audit,
                            audit_name,
                            sanitize_content,
                            audit_add,
                        )
                        total += count
                    elif name.startswith("word/media/") and not name.endswith("/"):
                        suffix = Path(name).suffix.lower()
                        if suffix not in IMAGE_EXTS:
                            raise ValueError(
                                f"DOCX contains unsupported embedded image type {suffix or '(no extension)'}: {name}"
                            )
                        data, count = sanitize_image_bytes(
                            data,
                            suffix,
                            rules,
                            audit,
                            audit_name,
                            classify_rule,
                            audit_add,
                            location_prefix=f"DOCX image {Path(name).name} OCR",
                        )
                        total += count
                    dst.writestr(info, data)

        # Validate that Microsoft Word's normal document model can reopen the package.
        Document(tmp_out)
        tmp_out.replace(fpath)
        return total
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise
