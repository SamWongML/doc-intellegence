"""Anchor slug generation: kebab-case, unique-within-document."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s-]")
_DASH_RUN = re.compile(r"[-\s]+")


def slug(text: str) -> str:
    """Return a kebab-case ASCII slug. Empty input → ``""``."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _NON_WORD.sub("", ascii_text).strip().lower()
    return _DASH_RUN.sub("-", cleaned)


def build_anchors(headings: list[str]) -> dict[str, str]:
    """Map ``heading_text → anchor``. Duplicates get ``-2``, ``-3``, … suffixes."""
    counts: dict[str, int] = {}
    out: dict[str, str] = {}
    for heading in headings:
        base = slug(heading) or "section"
        counts[base] = counts.get(base, 0) + 1
        suffix = "" if counts[base] == 1 else f"-{counts[base]}"
        out[heading] = f"{base}{suffix}"
    return out


__all__ = ["build_anchors", "slug"]
