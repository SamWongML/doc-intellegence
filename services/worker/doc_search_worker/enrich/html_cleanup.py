"""Strip docs-site chrome from Markdown after Trafilatura extraction.

Patterns are conservative: each one matches a whole line so we don't
accidentally chew into surrounding prose. The blocklist targets the most
common docs-site footers / nav residue: ``Edit this page``, ``Previous`` /
``Next`` link rows, ``Was this helpful?``, and orphan nav lists at the top
of the body.
"""

from __future__ import annotations

import re

_BLOCKLIST: tuple[re.Pattern[str], ...] = (
    re.compile(r"^.*Edit this page(?: on GitHub)?.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*Was this (?:helpful|page helpful)\??.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Previous\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Next\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*On this page\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Table of contents\s*$", re.IGNORECASE | re.MULTILINE),
)

_BLANK_RUN = re.compile(r"\n{3,}")
_LEADING_NAV = re.compile(
    r"\A(?:\s*[-*]\s+[^\n]+\n)+(?=\n*#)",
    re.MULTILINE,
)


def strip_chrome(markdown: str) -> str:
    """Apply the blocklist + collapse the resulting blank-line runs."""
    if not markdown:
        return markdown
    body = markdown
    for pat in _BLOCKLIST:
        body = pat.sub("", body)
    body = _LEADING_NAV.sub("", body, count=1)
    body = _BLANK_RUN.sub("\n\n", body)
    return body.strip() + "\n"


__all__ = ["strip_chrome"]
