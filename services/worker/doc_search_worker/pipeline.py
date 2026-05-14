"""Job pipeline orchestration: fetch → parse → enrich → handoff.

The pipeline collects ``ProcessedDocument``s in memory then flushes them to
``RagEmbeddingClient.ingest_documents`` in batches of 50. It also returns a
JSONL artifact that the runner uploads to S3 (``artifacts/...`` key).

Source routing
--------------

============================= =============================================
``source.type``               handler
============================= =============================================
``github``                    clone + iter Markdown files (Phase 1)
``openapi``                   fetch spec, iter operations (Phase 1)
``llms_full``                 ``llms-full.txt`` fast path or ``llms.txt``
                              index → HTML per-URL handling
``http_url`` + ``light``      Trafilatura; on empty output, requeue to heavy
``http_url`` + ``heavy``      Crawl4AI (headless Chromium)
``http_url`` PDF/Office       Docling on heavy; requeue on light (Phase 3)
============================= =============================================
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from doc_search_shared.clients import RagEmbeddingClient
from doc_search_shared.models import Job, ProcessedDocument

from . import hashing
from .enrich.anchors import build_anchors
from .enrich.breadcrumbs import breadcrumbs_from_path
from .enrich.code_blocks import dedupe_tags
from .logging_utils import log
from .parsers import docling_parser, html_trafilatura
from .parsers.markdown import parse_markdown
from .parsers.openapi import OpenapiOperation, iter_operations, short_summary
from .sources import github as github_source
from .sources import http_url as http_url_source
from .sources import llms_txt as llms_txt_source
from .sources import openapi as openapi_source

BATCH_SIZE = 50


@dataclass(slots=True)
class JobOutcome:
    docs_total: int
    docs_processed: int
    docs_failed: int
    chunk_count: int
    artifact_jsonl: bytes
    documents: list[ProcessedDocument]
    requeue_heavy: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Produced:
    documents: list[ProcessedDocument]
    failed: int
    requeue_heavy: list[str] = field(default_factory=list)


async def process_job(job: Job, *, client: RagEmbeddingClient) -> JobOutcome:
    """Run the full fetch→parse→enrich→handoff pipeline for one ``Job``."""
    log.info(
        "pipeline.start",
        job_id=job.job_id,
        library_id=job.library_id,
        source_type=job.source.type,
        profile=job.profile,
    )
    produced = await _produce(job)
    documents = produced.documents

    log.info(
        "pipeline.parsed",
        job_id=job.job_id,
        documents=len(documents),
        failed=produced.failed,
        requeue_heavy=len(produced.requeue_heavy),
    )

    ingested_total = 0
    chunk_total = 0
    for batch in _batched(documents, BATCH_SIZE):
        ingest = await client.ingest_documents(
            list(batch),
            library_id=job.library_id,
            version=job.version,
        )
        ingested_total += ingest.ingested
        chunk_total += ingest.chunk_count

    # Phase-6 will diff `document_id`s against the chunk_inventory; for now log
    # the incoming set so the wiring is observable.
    log.info(
        "pipeline.inventory_diff_stub",
        job_id=job.job_id,
        incoming=[d.document_id for d in documents],
    )

    return JobOutcome(
        docs_total=len(documents),
        docs_processed=ingested_total,
        docs_failed=produced.failed,
        chunk_count=chunk_total,
        artifact_jsonl=_to_jsonl(documents),
        documents=documents,
        requeue_heavy=produced.requeue_heavy,
    )


async def _produce(job: Job) -> _Produced:
    src = job.source
    if src.type == "github":
        return _collect(_from_github(job))
    if src.type == "openapi":
        return _collect(_from_openapi(job))
    if src.type == "http_url":
        return await _from_http_url(job)
    if src.type == "llms_full":
        return await _from_llms_full(job)
    raise NotImplementedError(f"source type {src.type!r} not supported")


def _collect(stream: Iterator[ProcessedDocument | None]) -> _Produced:
    docs: list[ProcessedDocument] = []
    failed = 0
    for item in stream:
        if item is None:
            failed += 1
        else:
            docs.append(item)
    return _Produced(documents=docs, failed=failed)


def _from_github(job: Job) -> Iterator[ProcessedDocument | None]:
    src = job.source
    for record in github_source.iter_files(src.url, src.ref, src.doc_paths):
        try:
            yield build_markdown_document(
                job=job,
                rel_path=record.rel_path,
                raw=record.data,
                source_url=record.source_url,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "pipeline.markdown_error",
                job_id=job.job_id,
                path=record.rel_path,
                error=str(exc),
            )
            yield None


def _from_openapi(job: Job) -> Iterator[ProcessedDocument]:
    src = job.source
    url = src.openapi_url or src.url
    source = openapi_source.fetch_and_resolve(url)
    for op in iter_operations(source.spec):
        yield build_openapi_document(job=job, op=op, base_url=source.raw_url)


async def _from_http_url(job: Job) -> _Produced:
    docs: list[ProcessedDocument] = []
    failed = 0
    requeue: list[str] = []
    for page in http_url_source.iter_pages(
        job.source.url,
        doc_paths=job.source.doc_paths or None,
    ):
        try:
            maybe_doc = await _html_page_to_document(job, page)
        except Exception as exc:
            log.warning(
                "pipeline.html_error",
                job_id=job.job_id,
                url=page.url,
                error=str(exc),
            )
            failed += 1
            continue
        if maybe_doc is None:
            requeue.append(page.url)
            continue
        docs.append(maybe_doc)
    return _Produced(documents=docs, failed=failed, requeue_heavy=requeue)


async def _from_llms_full(job: Job) -> _Produced:
    result = llms_txt_source.fetch(job.source.url)
    if isinstance(result, llms_txt_source.LlmsFullDoc):
        full_doc = build_llms_full_document(job=job, full=result)
        return _Produced(documents=[full_doc], failed=0)
    # Index path: crawl each URL with the same profile rules.
    docs: list[ProcessedDocument] = []
    failed = 0
    requeue: list[str] = []
    for url in result.urls:
        for page in http_url_source.iter_pages(url):
            try:
                maybe_doc = await _html_page_to_document(job, page)
            except Exception as exc:
                log.warning(
                    "pipeline.html_error",
                    job_id=job.job_id,
                    url=page.url,
                    error=str(exc),
                )
                failed += 1
                continue
            if maybe_doc is None:
                requeue.append(page.url)
            else:
                docs.append(maybe_doc)
    return _Produced(documents=docs, failed=failed, requeue_heavy=requeue)


async def _html_page_to_document(
    job: Job, page: http_url_source.FetchedPage
) -> ProcessedDocument | None:
    """Profile-aware page → ProcessedDocument routing.

    PDF/Office responses go to Docling on the heavy queue; HTML stays on the
    Trafilatura (light) / Crawl4AI (heavy) split. Returns ``None`` when light
    extraction fails (or a binary doc is seen on light) so the runner can
    requeue the URL onto the heavy queue.
    """
    if docling_parser.is_pdf_or_office(page.content_type):
        if job.profile == "light":
            log.info(
                "pipeline.binary_doc_requeue",
                job_id=job.job_id,
                url=page.url,
                content_type=page.content_type,
            )
            return None
        return _pdf_office_to_document(job, page)

    if job.profile == "heavy":
        from .parsers import html_crawl4ai

        crawled = await html_crawl4ai.fetch_and_extract(page.url)
        return build_html_document(
            job=job,
            url=page.url,
            title=crawled.title,
            markdown=crawled.markdown,
            anchors=crawled.anchors,
        )
    # light profile
    extracted = html_trafilatura.extract(page.html)
    if extracted is None:
        log.info(
            "pipeline.trafilatura_empty",
            job_id=job.job_id,
            url=page.url,
        )
        return None
    return build_html_document(
        job=job,
        url=page.url,
        title=extracted.title,
        markdown=extracted.markdown,
        anchors=extracted.anchors,
    )


def _pdf_office_to_document(job: Job, page: http_url_source.FetchedPage) -> ProcessedDocument:
    """Convert a PDF/Office FetchedPage via Docling on the heavy queue."""
    if page.content:
        parsed = docling_parser.parse_bytes(page.content, content_type=page.content_type)
    else:
        # Fallback: let Docling re-fetch the URL itself. Used when the source
        # iterator did not buffer bytes (tests, future streaming sources).
        parsed = docling_parser.parse(page.url)
    log.info(
        "pipeline.docling_parsed",
        job_id=job.job_id,
        url=page.url,
        pages=parsed.page_count,
    )
    return build_docling_document(job=job, url=page.url, parsed=parsed)


def build_markdown_document(
    *,
    job: Job,
    rel_path: str,
    raw: bytes,
    source_url: str,
) -> ProcessedDocument:
    """Parse + enrich one Markdown file into a ``ProcessedDocument``."""
    parsed = parse_markdown(raw.decode("utf-8", errors="replace"))
    crumbs = breadcrumbs_from_path(rel_path)
    anchors = build_anchors([text for _, text in parsed.headings if text])
    langs = dedupe_tags(parsed.code_languages)
    doc_id = hashing.document_id(job.library_id, source_url)
    return ProcessedDocument(
        document_id=doc_id,
        library_id=job.library_id,
        version=job.version,
        source_url=source_url,
        title=parsed.title,
        breadcrumbs=crumbs,
        doc_type="guide",
        language_tags=langs,
        markdown=parsed.canonical,
        anchors=anchors,
        content_hash=hashing.content_hash(parsed.canonical),
        extracted_at=datetime.now(UTC),
    )


def build_openapi_document(
    *,
    job: Job,
    op: OpenapiOperation,
    base_url: str,
) -> ProcessedDocument:
    """Build one ``ProcessedDocument`` from a parsed OpenAPI operation."""
    fragment = op.operation_id or f"{op.method.lower()}-{op.path}"
    source_url = f"{base_url}#operation:{fragment}"
    doc_id = hashing.document_id(job.library_id, source_url)
    heading_texts = [
        f"{op.method} {op.path}",
        "Parameters",
        "Request body",
        "Responses",
        "Security",
    ]
    return ProcessedDocument(
        document_id=doc_id,
        library_id=job.library_id,
        version=job.version,
        source_url=source_url,
        title=f"{op.method} {op.path}",
        breadcrumbs=list(op.tags),
        doc_type="openapi_endpoint",
        language_tags=[],
        markdown=op.markdown,
        anchors=build_anchors(heading_texts),
        openapi_spec=op.spec,
        openapi_summary=short_summary(op),
        content_hash=hashing.content_hash(op.markdown),
        extracted_at=datetime.now(UTC),
    )


def build_html_document(
    *,
    job: Job,
    url: str,
    title: str,
    markdown: str,
    anchors: dict[str, str],
) -> ProcessedDocument:
    """Build a ``ProcessedDocument`` from extracted HTML output."""
    canonical = hashing.normalize_whitespace(markdown)
    doc_id = hashing.document_id(job.library_id, url)
    return ProcessedDocument(
        document_id=doc_id,
        library_id=job.library_id,
        version=job.version,
        source_url=url,
        title=title or "Untitled",
        breadcrumbs=[],
        doc_type="guide",
        language_tags=[],
        markdown=canonical,
        anchors=anchors,
        content_hash=hashing.content_hash(canonical),
        extracted_at=datetime.now(UTC),
    )


def build_docling_document(
    *,
    job: Job,
    url: str,
    parsed: docling_parser.DoclingResult,
) -> ProcessedDocument:
    """Build a ``ProcessedDocument`` from a Docling conversion result."""
    canonical = hashing.normalize_whitespace(parsed.markdown)
    doc_id = hashing.document_id(job.library_id, url)
    return ProcessedDocument(
        document_id=doc_id,
        library_id=job.library_id,
        version=job.version,
        source_url=url,
        title=parsed.title or "Untitled",
        breadcrumbs=[],
        doc_type="reference",
        language_tags=[],
        markdown=canonical,
        anchors=parsed.anchors,
        content_hash=hashing.content_hash(canonical),
        extracted_at=datetime.now(UTC),
    )


def build_llms_full_document(
    *,
    job: Job,
    full: llms_txt_source.LlmsFullDoc,
) -> ProcessedDocument:
    """Build one ``ProcessedDocument`` from an ``llms-full.txt`` body."""
    parsed = parse_markdown(full.markdown, default_title="llms-full")
    doc_id = hashing.document_id(job.library_id, full.full_url)
    return ProcessedDocument(
        document_id=doc_id,
        library_id=job.library_id,
        version=job.version,
        source_url=full.full_url,
        title=parsed.title,
        breadcrumbs=[],
        doc_type="guide",
        language_tags=dedupe_tags(parsed.code_languages),
        markdown=parsed.canonical,
        anchors=build_anchors([text for _, text in parsed.headings if text]),
        content_hash=hashing.content_hash(parsed.canonical),
        extracted_at=datetime.now(UTC),
    )


def _batched(docs: list[ProcessedDocument], size: int) -> Iterator[list[ProcessedDocument]]:
    for i in range(0, len(docs), size):
        yield docs[i : i + size]


def _to_jsonl(docs: Iterable[ProcessedDocument]) -> bytes:
    buf = io.BytesIO()
    for d in docs:
        buf.write(d.model_dump_json().encode("utf-8"))
        buf.write(b"\n")
    return buf.getvalue()


__all__ = [
    "BATCH_SIZE",
    "JobOutcome",
    "build_docling_document",
    "build_html_document",
    "build_llms_full_document",
    "build_markdown_document",
    "build_openapi_document",
    "process_job",
]
