"""Pipeline routing for ``http_url`` / ``llms_full`` sources (Phase 2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal

import pytest
from doc_search_shared.clients import FakeRagEmbeddingClient
from doc_search_shared.models import Job, JobSource
from doc_search_worker import pipeline
from doc_search_worker.sources import http_url as http_url_source
from doc_search_worker.sources import llms_txt as llms_txt_source


def _make_job(source: JobSource, *, profile: Literal["light", "heavy"] = "light") -> Job:
    return Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        version="v15.1.0",
        source=source,
        mode="full",
        profile=profile,
        created_at=datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC),
    )


def _stub_pages(*pages: http_url_source.FetchedPage) -> object:
    def _iter(*_a: object, **_kw: object) -> Iterator[http_url_source.FetchedPage]:
        yield from pages

    return _iter


@pytest.mark.asyncio
async def test_http_url_light_uses_trafilatura(
    monkeypatch: pytest.MonkeyPatch, nextjs_html: str
) -> None:
    page = http_url_source.FetchedPage(
        url="https://docs.example.com/middleware",
        html=nextjs_html,
        content_type="text/html",
        status_code=200,
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))
    job = _make_job(
        JobSource(type="http_url", url="https://docs.example.com/middleware"),
        profile="light",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 1
    [doc] = outcome.documents
    assert doc.title == "Middleware"
    assert doc.anchors.get("Using JWT") == "using-jwt"
    assert "edit this page" not in doc.markdown.lower()
    assert "was this helpful" not in doc.markdown.lower()
    assert outcome.requeue_heavy == []


@pytest.mark.asyncio
async def test_http_url_light_requeues_to_heavy_on_empty_extract(
    monkeypatch: pytest.MonkeyPatch, spa_html: str
) -> None:
    page = http_url_source.FetchedPage(
        url="https://spa.example/app",
        html=spa_html,
        content_type="text/html",
        status_code=200,
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))
    job = _make_job(
        JobSource(type="http_url", url="https://spa.example/app"),
        profile="light",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 0
    assert outcome.requeue_heavy == ["https://spa.example/app"]


@pytest.mark.asyncio
async def test_http_url_heavy_uses_crawl4ai(
    monkeypatch: pytest.MonkeyPatch, spa_html: str
) -> None:
    page = http_url_source.FetchedPage(
        url="https://spa.example/app",
        html=spa_html,
        content_type="text/html",
        status_code=200,
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))

    from doc_search_worker.parsers import html_crawl4ai

    async def fake_crawl(url: str, **_kw: object) -> html_crawl4ai.CrawledHtml:
        return html_crawl4ai.CrawledHtml(
            title="Rendered SPA",
            markdown="# Rendered SPA\n\nFully hydrated content.\n",
            html="<h1 id='top'>Rendered SPA</h1>",
            anchors={"Rendered SPA": "top"},
        )

    monkeypatch.setattr(html_crawl4ai, "fetch_and_extract", fake_crawl)
    job = _make_job(
        JobSource(type="http_url", url="https://spa.example/app"),
        profile="heavy",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 1
    [doc] = outcome.documents
    assert doc.title == "Rendered SPA"
    assert doc.anchors == {"Rendered SPA": "top"}
    assert outcome.requeue_heavy == []


@pytest.mark.asyncio
async def test_llms_full_fast_path_skips_html(
    monkeypatch: pytest.MonkeyPatch, llms_full_text: str
) -> None:
    def fake_fetch(base_url: str, **_kw: object) -> llms_txt_source.LlmsFullDoc:
        return llms_txt_source.LlmsFullDoc(
            base_url=base_url,
            full_url=base_url.rstrip("/") + "/llms-full.txt",
            markdown=llms_full_text,
        )

    monkeypatch.setattr(llms_txt_source, "fetch", fake_fetch)
    job = _make_job(JobSource(type="llms_full", url="https://docs.anthropic.com"))
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 1
    [doc] = outcome.documents
    assert doc.title == "Anthropic Docs — All-in-one"
    assert "Messages API" in doc.markdown
    assert "bash" in doc.language_tags


@pytest.mark.asyncio
async def test_llms_index_path_crawls_urls(
    monkeypatch: pytest.MonkeyPatch, nextjs_html: str
) -> None:
    def fake_llms(base_url: str, **_kw: object) -> llms_txt_source.LlmsTxtIndex:
        return llms_txt_source.LlmsTxtIndex(
            base_url=base_url,
            txt_url=base_url + "/llms.txt",
            title="Example",
            urls=["https://docs.example.com/middleware"],
        )

    monkeypatch.setattr(llms_txt_source, "fetch", fake_llms)
    page = http_url_source.FetchedPage(
        url="https://docs.example.com/middleware",
        html=nextjs_html,
        content_type="text/html",
        status_code=200,
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))

    job = _make_job(
        JobSource(type="llms_full", url="https://docs.example.com"),
        profile="light",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 1
    [doc] = outcome.documents
    assert doc.source_url == "https://docs.example.com/middleware"
