"""HTTP and llms.txt sources: respx-mocked fetches + sitemap expansion."""

from __future__ import annotations

import httpx
import pytest
import respx
from doc_search_worker.sources import http_url, llms_txt


@respx.mock
def test_iter_pages_single_url(nextjs_html: str) -> None:
    respx.get("https://docs.example.com/middleware").mock(
        return_value=httpx.Response(200, text=nextjs_html, headers={"content-type": "text/html"}),
    )
    pages = list(http_url.iter_pages("https://docs.example.com/middleware"))
    assert len(pages) == 1
    assert pages[0].html == nextjs_html
    assert pages[0].status_code == 200
    assert "text/html" in pages[0].content_type


@respx.mock
def test_iter_pages_skips_error_status() -> None:
    respx.get("https://docs.example.com/missing").mock(return_value=httpx.Response(404))
    pages = list(http_url.iter_pages("https://docs.example.com/missing"))
    assert pages == []


@respx.mock
def test_iter_pages_expands_sitemap() -> None:
    sitemap = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example.com/a</loc></url>
  <url><loc>https://docs.example.com/b</loc></url>
  <url><loc>https://other.example.com/c</loc></url>
</urlset>"""
    respx.get("https://docs.example.com/sitemap.xml").mock(
        return_value=httpx.Response(200, text=sitemap)
    )
    respx.get("https://docs.example.com/a").mock(return_value=httpx.Response(200, text="A"))
    respx.get("https://docs.example.com/b").mock(return_value=httpx.Response(200, text="B"))
    pages = list(
        http_url.iter_pages(
            "https://docs.example.com/sitemap.xml",
            doc_paths=["docs.example.com"],
        )
    )
    urls = sorted(p.url for p in pages)
    assert urls == [
        "https://docs.example.com/a",
        "https://docs.example.com/b",
    ]


@respx.mock
def test_iter_pages_sitemap_breadth_limit() -> None:
    locs = "".join(f"<url><loc>https://x.example/{i}</loc></url>" for i in range(10))
    sitemap = f"<?xml version='1.0'?><urlset>{locs}</urlset>"
    respx.get("https://x.example/sitemap.xml").mock(return_value=httpx.Response(200, text=sitemap))
    for i in range(10):
        respx.get(f"https://x.example/{i}").mock(return_value=httpx.Response(200, text=str(i)))
    pages = list(http_url.iter_pages("https://x.example/sitemap.xml", breadth=3))
    assert len(pages) == 3


@respx.mock
def test_llms_txt_fetch_full_path(llms_full_text: str) -> None:
    respx.get("https://docs.anthropic.com/llms-full.txt").mock(
        return_value=httpx.Response(200, text=llms_full_text)
    )
    result = llms_txt.fetch("https://docs.anthropic.com")
    assert isinstance(result, llms_txt.LlmsFullDoc)
    assert "Messages API" in result.markdown
    assert result.full_url.endswith("/llms-full.txt")


@respx.mock
def test_llms_txt_falls_back_to_index(llms_index_text: str) -> None:
    respx.get("https://docs.example.com/llms-full.txt").mock(
        return_value=httpx.Response(404),
    )
    respx.get("https://docs.example.com/llms.txt").mock(
        return_value=httpx.Response(200, text=llms_index_text),
    )
    result = llms_txt.fetch("https://docs.example.com")
    assert isinstance(result, llms_txt.LlmsTxtIndex)
    assert result.title == "Example Docs Index"
    assert "https://docs.example.com/quickstart" in result.urls
    assert "https://docs.example.com/api" in result.urls


@respx.mock
def test_llms_txt_empty_full_falls_back(llms_index_text: str) -> None:
    """An empty 200 body should NOT short-circuit the full path."""
    respx.get("https://docs.example.com/llms-full.txt").mock(
        return_value=httpx.Response(200, text="   \n"),
    )
    respx.get("https://docs.example.com/llms.txt").mock(
        return_value=httpx.Response(200, text=llms_index_text),
    )
    result = llms_txt.fetch("https://docs.example.com")
    assert isinstance(result, llms_txt.LlmsTxtIndex)


@respx.mock
def test_llms_txt_raises_when_neither_present() -> None:
    respx.get("https://nope.example/llms-full.txt").mock(return_value=httpx.Response(404))
    respx.get("https://nope.example/llms.txt").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPError):
        llms_txt.fetch("https://nope.example")
