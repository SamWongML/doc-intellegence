"""HTML → Markdown via Trafilatura (BSD, in-process, no GPU).

Used on the light worker profile. Returns ``None`` when extraction yields
empty or near-empty output so the pipeline can fall back to the Chromium
path on the heavy queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import trafilatura

from ..enrich.html_anchors import extract_html_anchors, extract_title
from ..enrich.html_cleanup import strip_chrome

MIN_OUTPUT_CHARS = 200


@dataclass(slots=True)
class ExtractedHtml:
    """Result of HTML extraction. ``language_tags`` left empty for the
    parser; the pipeline fills it from fenced code blocks if needed."""

    title: str
    markdown: str
    anchors: dict[str, str] = field(default_factory=dict)


def extract(html: str, *, default_title: str = "Untitled") -> ExtractedHtml | None:
    """Run Trafilatura. Return ``None`` if output is too thin for fallback."""
    raw_md = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_comments=False,
    )
    if not raw_md or len(raw_md.strip()) < MIN_OUTPUT_CHARS:
        return None
    cleaned = strip_chrome(raw_md)
    anchors = extract_html_anchors(html)
    title = extract_title(html) or default_title
    return ExtractedHtml(title=title, markdown=cleaned, anchors=anchors)


__all__ = ["MIN_OUTPUT_CHARS", "ExtractedHtml", "extract"]
