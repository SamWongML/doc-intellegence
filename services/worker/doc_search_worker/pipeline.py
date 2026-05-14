"""Job pipeline orchestration: fetch → parse → enrich → handoff.

The pipeline collects ``ProcessedDocument``s in memory then flushes them to
``RagEmbeddingClient.ingest_documents`` in batches of 50. It also returns a
JSONL artifact that the runner uploads to S3 (``artifacts/...`` key).
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from doc_search_shared.clients import RagEmbeddingClient
from doc_search_shared.models import Job, ProcessedDocument

from . import hashing
from .enrich.anchors import build_anchors
from .enrich.breadcrumbs import breadcrumbs_from_path
from .enrich.code_blocks import dedupe_tags
from .logging_utils import log
from .parsers.markdown import parse_markdown
from .parsers.openapi import OpenapiOperation, iter_operations, short_summary
from .sources import github as github_source
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


async def process_job(job: Job, *, client: RagEmbeddingClient) -> JobOutcome:
    """Run the full fetch→parse→enrich→handoff pipeline for one ``Job``."""
    log.info(
        "pipeline.start",
        job_id=job.job_id,
        library_id=job.library_id,
        source_type=job.source.type,
    )
    documents: list[ProcessedDocument] = []
    failed = 0
    for produced in _produce(job):
        if produced is None:
            failed += 1
        else:
            documents.append(produced)

    log.info(
        "pipeline.parsed",
        job_id=job.job_id,
        documents=len(documents),
        failed=failed,
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
        docs_failed=failed,
        chunk_count=chunk_total,
        artifact_jsonl=_to_jsonl(documents),
        documents=documents,
    )


def _produce(job: Job) -> Iterator[ProcessedDocument | None]:
    src = job.source
    if src.type == "github":
        yield from _from_github(job)
    elif src.type == "openapi":
        yield from _from_openapi(job)
    else:
        raise NotImplementedError(f"source type {src.type!r} not supported in Phase 1")


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
    "build_markdown_document",
    "build_openapi_document",
    "process_job",
]
