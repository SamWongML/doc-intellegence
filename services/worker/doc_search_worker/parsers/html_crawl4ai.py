"""HTML → Markdown via Crawl4AI (Chromium-backed, heavy profile only).

Crawl4AI ships its own Playwright driver. Importing it eagerly would pull
Chromium into every container — we keep the import lazy so the light image
stays small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..enrich.html_anchors import extract_html_anchors, extract_title
from ..enrich.html_cleanup import strip_chrome

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


@dataclass(slots=True)
class CrawledHtml:
    title: str
    markdown: str
    html: str
    anchors: dict[str, str] = field(default_factory=dict)


async def fetch_and_extract(url: str, *, headless: bool = True) -> CrawledHtml:
    """Open ``url`` in headless Chromium, return rendered HTML + Markdown.

    Lazily imports ``crawl4ai`` so the light worker image doesn't need it.
    Raises ``RuntimeError`` if the crawl returns no usable content.
    """
    from crawl4ai import (
        AsyncWebCrawler,
        BrowserConfig,
        CrawlerRunConfig,
    )

    browser = BrowserConfig(headless=headless)
    run = CrawlerRunConfig(word_count_threshold=10)
    async with AsyncWebCrawler(config=browser) as crawler:
        result = await crawler.arun(url=url, config=run)
    if not getattr(result, "success", False):
        raise RuntimeError(f"crawl4ai failed for {url}: {getattr(result, 'error_message', '')}")
    markdown = getattr(result, "markdown", None) or ""
    if hasattr(markdown, "raw_markdown"):
        markdown = markdown.raw_markdown
    rendered_html = getattr(result, "html", "") or ""
    anchors = extract_html_anchors(rendered_html)
    title = extract_title(rendered_html) or url
    return CrawledHtml(
        title=title,
        markdown=strip_chrome(str(markdown)),
        html=rendered_html,
        anchors=anchors,
    )


__all__ = ["CrawledHtml", "fetch_and_extract"]
