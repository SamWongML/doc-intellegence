"""Extract real ``<hN id="...">`` anchors and ``<title>`` from raw HTML.

We parse the source HTML once with selectolax/lexbor before Trafilatura
strips it. The resulting ``heading → anchor`` map is attached to the
``ProcessedDocument`` so consumers can deep-link back to the canonical doc
URL even when the body has been Markdownified.
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from .anchors import build_anchors

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def extract_html_anchors(html: str) -> dict[str, str]:
    """Return a ``heading_text → anchor_id`` map for all id-bearing headings.

    For headings without an ``id``, fall back to the auto-generated kebab slug
    (so callers always get a deterministic anchor for every heading).
    """
    if not html:
        return {}
    parser = HTMLParser(html)
    real: dict[str, str] = {}
    ordered_texts: list[str] = []
    for tag in _HEADING_TAGS:
        for node in parser.css(f"{tag}[id]"):
            text = node.text(strip=True)
            anchor = (node.attributes.get("id") or "").strip()
            if not text or not anchor:
                continue
            real.setdefault(text, anchor)
    # Build slug fallback for any headings without an id.
    for tag in _HEADING_TAGS:
        for node in parser.css(tag):
            text = node.text(strip=True)
            if text and text not in real and text not in ordered_texts:
                ordered_texts.append(text)
    fallback = build_anchors(ordered_texts) if ordered_texts else {}
    out: dict[str, str] = {**fallback, **real}
    return out


def extract_title(html: str) -> str:
    """Return the document title — prefer ``<h1>`` then ``<title>``."""
    if not html:
        return ""
    parser = HTMLParser(html)
    h1 = parser.css_first("h1")
    if h1 is not None:
        text = h1.text(strip=True)
        if text:
            return text
    title = parser.css_first("title")
    if title is not None:
        text = title.text(strip=True)
        if text:
            return text
    return ""


__all__ = ["extract_html_anchors", "extract_title"]
