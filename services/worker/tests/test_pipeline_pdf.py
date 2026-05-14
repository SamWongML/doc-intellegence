"""Pipeline routing for PDF/Office binary sources (Phase 3)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal

import pytest
from doc_search_shared.clients import FakeRagEmbeddingClient
from doc_search_shared.models import Job, JobSource
from doc_search_worker import pipeline
from doc_search_worker.parsers import docling_parser
from doc_search_worker.sources import http_url as http_url_source


def _make_job(source: JobSource, *, profile: Literal["light", "heavy"] = "light") -> Job:
    return Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/acme/widget",
        version="v1.0.0",
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
async def test_pdf_on_light_profile_requeues_to_heavy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = http_url_source.FetchedPage(
        url="https://example.com/spec.pdf",
        html="",
        content_type="application/pdf",
        status_code=200,
        content=b"%PDF-1.4 fake",
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))

    job = _make_job(
        JobSource(type="http_url", url="https://example.com/spec.pdf"),
        profile="light",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert outcome.docs_total == 0
    assert outcome.docs_failed == 0
    assert outcome.requeue_heavy == ["https://example.com/spec.pdf"]


@pytest.mark.asyncio
async def test_pdf_on_heavy_profile_goes_through_docling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = http_url_source.FetchedPage(
        url="https://example.com/spec.pdf",
        html="",
        content_type="application/pdf; charset=binary",
        status_code=200,
        content=b"%PDF-1.4 fake",
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))

    captured: dict[str, object] = {}

    def fake_parse_bytes(
        data: bytes, *, content_type: str, **_kw: object
    ) -> docling_parser.DoclingResult:
        captured["data"] = data
        captured["content_type"] = content_type
        return docling_parser.DoclingResult(
            title="Widget Spec Sheet",
            markdown="# Widget Spec Sheet\n\n| Param | Value |\n|-------|-------|\n| V     | 5     |\n",
            anchors={"Widget Spec Sheet": "page-1", "Dimensions": "page-3"},
            page_count=3,
        )

    monkeypatch.setattr(docling_parser, "parse_bytes", fake_parse_bytes)

    job = _make_job(
        JobSource(type="http_url", url="https://example.com/spec.pdf"),
        profile="heavy",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())

    assert captured["data"] == b"%PDF-1.4 fake"
    assert captured["content_type"] == "application/pdf; charset=binary"
    assert outcome.docs_total == 1
    [doc] = outcome.documents
    assert doc.title == "Widget Spec Sheet"
    assert doc.doc_type == "reference"
    assert doc.anchors == {"Widget Spec Sheet": "page-1", "Dimensions": "page-3"}
    assert "| Param | Value |" in doc.markdown
    assert outcome.requeue_heavy == []


@pytest.mark.asyncio
async def test_pdf_on_heavy_falls_back_to_url_when_no_bytes_buffered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = http_url_source.FetchedPage(
        url="https://example.com/spec.pdf",
        html="",
        content_type="application/pdf",
        status_code=200,
        content=b"",
    )
    monkeypatch.setattr(http_url_source, "iter_pages", _stub_pages(page))

    seen_urls: list[str] = []

    def fake_parse(source: str, **_kw: object) -> docling_parser.DoclingResult:
        seen_urls.append(source)
        return docling_parser.DoclingResult(
            title="Remote PDF",
            markdown="# Remote PDF\n",
            anchors={"Remote PDF": "page-1"},
            page_count=1,
        )

    monkeypatch.setattr(docling_parser, "parse", fake_parse)

    job = _make_job(
        JobSource(type="http_url", url="https://example.com/spec.pdf"),
        profile="heavy",
    )
    outcome = await pipeline.process_job(job, client=FakeRagEmbeddingClient())
    assert seen_urls == ["https://example.com/spec.pdf"]
    assert outcome.docs_total == 1


def test_build_docling_document_normalises_and_sets_doc_type() -> None:
    job = _make_job(JobSource(type="http_url", url="https://example.com/spec.pdf"), profile="heavy")
    parsed = docling_parser.DoclingResult(
        title="Spec",
        markdown="# Spec\n\n\n\nTrailing blanks\n",
        anchors={"Spec": "page-1"},
        page_count=1,
    )
    doc = pipeline.build_docling_document(
        job=job, url="https://example.com/spec.pdf", parsed=parsed
    )
    assert doc.doc_type == "reference"
    assert doc.title == "Spec"
    assert doc.anchors == {"Spec": "page-1"}
    assert doc.markdown.endswith("\n")
    assert "\n\n\n" not in doc.markdown  # collapsed
    assert doc.content_hash and len(doc.content_hash) == 64
