"""``llms-full.txt`` / ``llms.txt`` source.

Convention (https://llmstxt.org/):
* ``{base}/llms-full.txt`` — one canonical Markdown document. If present we
  return its body verbatim and skip HTML parsing entirely.
* ``{base}/llms.txt`` — Markdown index of URLs. Returns the list to crawl
  via the regular HTML path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from ..logging_utils import log
from .http_url import DEFAULT_TIMEOUT, USER_AGENT

_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"^\s*(?:-\s+)?(https?://\S+)\s*$", re.MULTILINE)


@dataclass(slots=True)
class LlmsFullDoc:
    """The base site exposed an ``llms-full.txt``: one big Markdown blob."""

    base_url: str
    full_url: str
    markdown: str


@dataclass(slots=True)
class LlmsTxtIndex:
    """Fallback path: the base site exposed ``llms.txt`` listing URLs."""

    base_url: str
    txt_url: str
    title: str
    urls: list[str]


LlmsResult = LlmsFullDoc | LlmsTxtIndex


def fetch(
    base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> LlmsResult:
    """Try ``llms-full.txt`` first; fall back to ``llms.txt``.

    Raises :class:`httpx.HTTPError` if neither file is reachable.
    """
    own_client = client is None
    cli = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        full_url = _join(base_url, "llms-full.txt")
        log.info("llms_txt.try_full", url=full_url)
        resp = cli.get(full_url)
        if resp.status_code == 200 and resp.text.strip():
            return LlmsFullDoc(base_url=base_url, full_url=full_url, markdown=resp.text)
        txt_url = _join(base_url, "llms.txt")
        log.info("llms_txt.try_index", url=txt_url)
        resp = cli.get(txt_url)
        resp.raise_for_status()
        title, urls = _parse_llms_txt(resp.text)
        log.info("llms_txt.index_parsed", url=txt_url, urls=len(urls))
        return LlmsTxtIndex(base_url=base_url, txt_url=txt_url, title=title, urls=urls)
    finally:
        if own_client:
            cli.close()


def _join(base: str, path: str) -> str:
    if not base.endswith("/"):
        base = base + "/"
    return urljoin(base, path)


def _parse_llms_txt(content: str) -> tuple[str, list[str]]:
    """Return ``(title, urls)``.

    The llms.txt spec uses an H1 for the title and Markdown links for URL
    entries. We also accept bare-URL lines for resilience.
    """
    title = "llms.txt"
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip() or title
            break
    seen: set[str] = set()
    urls: list[str] = []
    for url in _LINK_RE.findall(content):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    for match in _BARE_URL_RE.finditer(content):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return title, urls


__all__ = [
    "LlmsFullDoc",
    "LlmsResult",
    "LlmsTxtIndex",
    "fetch",
]
