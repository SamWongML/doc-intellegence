"""Round-trip tests for shared Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from doc_search_shared.models import (
    CodeBlock,
    Job,
    JobSource,
    JobStatus,
    ProcessedDocument,
)


def _now() -> datetime:
    return datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


def test_job_roundtrip() -> None:
    job = Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        version="v15.1.0",
        source=JobSource(
            type="github",
            url="https://github.com/vercel/next.js",
            ref="canary",
            doc_paths=["docs/**/*.mdx"],
        ),
        mode="full",
        profile="light",
        requested_by="alice",
        trace_id="trace-abc",
        created_at=_now(),
    )
    raw = job.model_dump_json()
    restored = Job.model_validate_json(raw)
    assert restored == job


def test_job_default_mode() -> None:
    job = Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        source=JobSource(type="http_url", url="https://example.com"),
        profile="heavy",
        created_at=_now(),
    )
    assert job.mode == "full"


def test_processed_document_roundtrip() -> None:
    doc = ProcessedDocument(
        document_id="d" * 64,
        library_id="/vercel/next.js",
        version="v15.1.0",
        source_url="https://nextjs.org/docs/routing",
        title="Routing",
        breadcrumbs=["App Router", "Routing"],
        doc_type="guide",
        language_tags=["en"],
        markdown="# Hello\n\nWorld.",
        anchors={"hello": "Hello"},
        content_hash="c" * 64,
        extracted_at=_now(),
    )
    raw = doc.model_dump_json()
    restored = ProcessedDocument.model_validate_json(raw)
    assert restored == doc


def test_job_status_defaults() -> None:
    status = JobStatus(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        state="queued",
    )
    assert status.docs_total == 0
    assert status.docs_processed == 0
    raw = status.model_dump_json()
    restored = JobStatus.model_validate_json(raw)
    assert restored == status


def test_code_block_optional_language() -> None:
    cb = CodeBlock(content="print('hi')")
    assert cb.language is None
    assert CodeBlock.model_validate_json(cb.model_dump_json()) == cb


def test_processed_document_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ProcessedDocument.model_validate(
            {
                "document_id": "x",
                "library_id": "/a/b",
                "source_url": "https://x",
                "title": "t",
                "doc_type": "guide",
                "markdown": "",
                "content_hash": "h",
                "extracted_at": _now(),
                "unknown": "field",
            }
        )
