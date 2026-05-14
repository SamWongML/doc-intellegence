"""HTTP source: fetch a single URL or expand a sitemap.

The source is intentionally dumb — it does not parse HTML, only retrieves
bytes. The pipeline picks a parser (Trafilatura on light, Crawl4AI on heavy)
based on ``job.profile``.

Sitemap expansion is bounded by ``breadth`` (max URLs returned) to keep crawl
jobs predictable. Nested sitemaps recurse once and contribute to the same
breadth budget.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from ..logging_utils import log

DEFAULT_TIMEOUT = 30.0
DEFAULT_BREADTH = 200
USER_AGENT = "doc-search-worker/2 (+https://github.com/samwongml/doc-intellegence)"

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_SITEMAP_TAG_RE = re.compile(r"<sitemap>", re.IGNORECASE)


@dataclass(slots=True)
class FetchedPage:
    """One fetched URL: canonical url + decoded HTML body + raw bytes.

    ``html`` is empty for non-text responses (PDF, Office binaries) so callers
    do not waste cycles attempting to decode binary data; use ``content`` for
    those formats.
    """

    url: str
    html: str
    content_type: str
    status_code: int
    content: bytes = b""


def iter_pages(
    url: str,
    *,
    doc_paths: list[str] | None = None,
    breadth: int = DEFAULT_BREADTH,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> Iterator[FetchedPage]:
    """Yield one ``FetchedPage`` per discovered URL.

    * If ``url`` looks like a sitemap (.xml or sitemap.xml), expand it.
    * Otherwise, yield a single page.
    * ``doc_paths`` is an optional list of substring filters to keep only
      matching URLs (e.g. ``["/docs/"]``).
    """
    own_client = client is None
    cli = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        if _looks_like_sitemap(url):
            urls = list(_expand_sitemap(cli, url, breadth=breadth))
            urls = _filter_urls(urls, doc_paths)
            log.info("http_url.sitemap_expanded", url=url, count=len(urls))
            for page_url in urls:
                page = _fetch_one(cli, page_url)
                if page is not None:
                    yield page
        else:
            page = _fetch_one(cli, url)
            if page is not None:
                yield page
    finally:
        if own_client:
            cli.close()


def _fetch_one(client: httpx.Client, url: str) -> FetchedPage | None:
    log.info("http_url.fetch", url=url)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        log.warning("http_url.fetch_error", url=url, error=str(exc))
        return None
    if resp.status_code >= 400:
        log.warning("http_url.fetch_status", url=url, status=resp.status_code)
        return None
    content_type = resp.headers.get("content-type", "")
    html = resp.text if _is_textual(content_type) else ""
    return FetchedPage(
        url=str(resp.url),
        html=html,
        content_type=content_type,
        status_code=resp.status_code,
        content=resp.content,
    )


def _is_textual(content_type: str) -> bool:
    primary = content_type.split(";", 1)[0].strip().lower()
    if not primary:
        return True  # assume text when the server is silent
    if primary.startswith("text/"):
        return True
    return primary in {
        "application/xml",
        "application/xhtml+xml",
        "application/json",
        "application/javascript",
        "application/ld+json",
    }


def _looks_like_sitemap(url: str) -> bool:
    lower = url.lower()
    return lower.endswith(".xml") or lower.endswith("/sitemap")


def _expand_sitemap(
    client: httpx.Client,
    url: str,
    *,
    breadth: int,
    _depth: int = 0,
) -> Iterator[str]:
    if _depth > 2:
        return
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        log.warning("http_url.sitemap_error", url=url, error=str(exc))
        return
    if resp.status_code >= 400:
        return
    body = resp.text
    locs = _LOC_RE.findall(body)
    nested = _SITEMAP_TAG_RE.search(body) is not None
    yielded = 0
    for loc in locs:
        if yielded >= breadth:
            return
        if nested and _looks_like_sitemap(loc):
            for sub in _expand_sitemap(client, loc, breadth=breadth - yielded, _depth=_depth + 1):
                if yielded >= breadth:
                    return
                yield sub
                yielded += 1
        else:
            yield loc
            yielded += 1


def _filter_urls(urls: list[str], doc_paths: list[str] | None) -> list[str]:
    if not doc_paths:
        return urls
    return [u for u in urls if any(pat in u for pat in doc_paths)]


__all__ = [
    "DEFAULT_BREADTH",
    "DEFAULT_TIMEOUT",
    "USER_AGENT",
    "FetchedPage",
    "iter_pages",
]
