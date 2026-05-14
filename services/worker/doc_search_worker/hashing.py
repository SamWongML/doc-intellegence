"""Content hashing + deterministic document ID generation.

* ``content_hash = sha256(normalize_whitespace(markdown))`` — used for change
  detection by Phase 6's incremental skip.
* ``document_id = sha256(library_id + source_url)`` — per `contracts.md` §B.
"""

from __future__ import annotations

import hashlib
import re

_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    """Strip trailing whitespace and collapse 3+ blank lines to a single blank.

    Idempotent: ``normalize_whitespace(normalize_whitespace(x)) == normalize_whitespace(x)``.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip() + "\n"


def content_hash(markdown: str) -> str:
    return hashlib.sha256(normalize_whitespace(markdown).encode("utf-8")).hexdigest()


def document_id(library_id: str, source_url: str) -> str:
    return hashlib.sha256(f"{library_id}\0{source_url}".encode()).hexdigest()


__all__ = ["content_hash", "document_id", "normalize_whitespace"]
