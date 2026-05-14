"""PDF/Office → Markdown via Docling (heavy profile only).

Docling pulls ~1-2 GB of model weights on first use and a heavy Python
dependency tree (torch, transformers, onnxruntime). We import it lazily so
the light worker image never carries the weight.

Output contract
---------------

* ``DoclingResult.markdown`` is canonical Markdown produced by
  ``DoclingDocument.export_to_markdown()`` — tables, code blocks and
  equations are already represented as their Markdown equivalents.
* ``DoclingResult.anchors`` maps each section heading to a ``page-N``
  pseudo-anchor (``"# Introduction" -> "page-3"``). Duplicate slugs get
  ``-2``, ``-3``, … suffixes, matching ``enrich.anchors.build_anchors``.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..enrich.anchors import slug

PDF_OFFICE_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)

# Maps a primary MIME type → tempfile suffix so Docling autodetects format
# from the path. Unknown binary types fall back to ``.bin`` (Docling will
# refuse, surfacing a real error rather than mis-parsing).
_EXT_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


@dataclass(slots=True)
class DoclingResult:
    """Parsed output of a single Docling conversion."""

    title: str
    markdown: str
    anchors: dict[str, str] = field(default_factory=dict)
    page_count: int = 0


def _primary(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def is_pdf_or_office(content_type: str) -> bool:
    """Return ``True`` if ``content_type`` denotes a PDF/Office binary doc."""
    if not content_type:
        return False
    return _primary(content_type) in PDF_OFFICE_CONTENT_TYPES


def ext_for_content_type(content_type: str) -> str:
    """Return the canonical file extension (including dot) for ``content_type``."""
    return _EXT_BY_CONTENT_TYPE.get(_primary(content_type), ".bin")


def parse(source: str | Path, *, converter: Any | None = None) -> DoclingResult:
    """Convert a document at ``source`` (URL or local path) via Docling.

    ``converter`` is injectable for testing; default lazily imports
    ``docling.document_converter.DocumentConverter``.
    """
    if converter is None:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
    result = converter.convert(str(source))
    return _build_result(result.document)


def parse_bytes(
    data: bytes,
    *,
    content_type: str,
    converter: Any | None = None,
) -> DoclingResult:
    """Convert raw ``data`` by writing to a tempfile with a suitable suffix.

    Docling 2.x sniffs format from the file extension, not magic bytes, so a
    correct suffix is required.
    """
    suffix = ext_for_content_type(content_type)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as fh:
        fh.write(data)
        fh.flush()
        return parse(fh.name, converter=converter)


def _build_result(doc: Any) -> DoclingResult:
    markdown = str(doc.export_to_markdown())
    title, anchors, page_count = _collect_structure(doc)
    return DoclingResult(
        title=title,
        markdown=markdown,
        anchors=anchors,
        page_count=page_count,
    )


def _collect_structure(doc: Any) -> tuple[str, dict[str, str], int]:
    """Walk the DoclingDocument once: find a title, page-pseudo anchors, page count."""
    title = "Untitled"
    anchors: dict[str, str] = {}
    counts: dict[str, int] = {}
    pages: set[int] = set()

    for item, _level in _iter_items(doc):
        page_no = _item_page(item)
        if page_no is not None:
            pages.add(page_no)
        if not _is_section_header(item):
            continue
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if title == "Untitled":
            title = text
        base = f"page-{page_no}" if page_no is not None else (slug(text) or "section")
        counts[base] = counts.get(base, 0) + 1
        suffix = "" if counts[base] == 1 else f"-{counts[base]}"
        anchors[text] = f"{base}{suffix}"

    return title, anchors, len(pages)


def _iter_items(doc: Any) -> Iterable[tuple[Any, int]]:
    fn = getattr(doc, "iterate_items", None)
    if fn is None:
        return ()
    try:
        return list(fn())
    except Exception:  # pragma: no cover - defensive against future docling shape changes
        return ()


def _item_page(item: Any) -> int | None:
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    first = prov[0]
    for attr in ("page_no", "page"):
        val = getattr(first, attr, None)
        if val is None:
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _is_section_header(item: Any) -> bool:
    label = getattr(item, "label", None)
    name = getattr(label, "name", None) if label is not None else None
    if isinstance(name, str):
        return name == "SECTION_HEADER"
    if isinstance(label, str):
        return label.upper() == "SECTION_HEADER"
    return False


__all__ = [
    "PDF_OFFICE_CONTENT_TYPES",
    "DoclingResult",
    "ext_for_content_type",
    "is_pdf_or_office",
    "parse",
    "parse_bytes",
]
