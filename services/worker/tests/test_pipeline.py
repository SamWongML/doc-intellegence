"""Pipeline orchestration: end-to-end with fake clients + injected source."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from doc_search_shared.clients import FakeRagEmbeddingClient
from doc_search_shared.models import Job, JobSource, ProcessedDocument
from doc_search_worker.parsers.openapi import iter_operations
from doc_search_worker.pipeline import (
    BATCH_SIZE,
    build_markdown_document,
    build_openapi_document,
    process_job,
)
from doc_search_worker.sources import github as github_source
from doc_search_worker.sources import openapi as openapi_source


@contextmanager
def _yield_path(path: Path) -> Iterator[Path]:
    yield path


def _now() -> datetime:
    return datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


def _make_job(source: JobSource, **kwargs: Any) -> Job:
    return Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        version="v15.1.0",
        source=source,
        mode="full",
        profile="light",
        created_at=_now(),
        **kwargs,
    )


def test_build_markdown_document_roundtrips_canonical(sample_repo_dir: Path) -> None:
    raw = (sample_repo_dir / "docs/app-router/routing/middleware.mdx").read_bytes()
    job = _make_job(JobSource(type="github", url="https://github.com/vercel/next.js"))
    doc = build_markdown_document(
        job=job,
        rel_path="docs/app-router/routing/middleware.mdx",
        raw=raw,
        source_url="https://github.com/vercel/next.js/blob/HEAD/docs/app-router/routing/middleware.mdx",
    )
    assert isinstance(doc, ProcessedDocument)
    assert doc.title == "Middleware"
    assert doc.breadcrumbs == ["App Router", "Routing"]
    assert "bash" in doc.language_tags
    assert doc.anchors  # at least one heading
    assert doc.content_hash and len(doc.content_hash) == 64
    assert doc.markdown.strip().startswith("# Welcome")


def test_build_openapi_document_attaches_full_spec(petstore_spec: dict[str, Any]) -> None:
    job = _make_job(JobSource(type="openapi", url="https://example.com/spec"))
    ops = list(iter_operations(petstore_spec))
    op = ops[0]
    doc = build_openapi_document(job=job, op=op, base_url="https://example.com/spec")
    assert doc.doc_type == "openapi_endpoint"
    assert doc.openapi_spec is not None
    assert doc.openapi_summary
    assert doc.title == f"{op.method} {op.path}"
    assert "operation:" in doc.source_url


@pytest.mark.asyncio
async def test_process_job_github_full_flow(
    monkeypatch: pytest.MonkeyPatch, sample_repo_dir: Path
) -> None:
    # Replace pygit2_clone with a no-op that yields our fixture dir directly.
    def fake_clone(url: str, ref: str | None) -> Any:
        return _yield_path(sample_repo_dir)

    monkeypatch.setattr(github_source, "pygit2_clone", fake_clone)
    client = FakeRagEmbeddingClient()
    job = _make_job(
        JobSource(
            type="github",
            url="https://github.com/vercel/next.js",
            doc_paths=["docs/**/*.md", "docs/**/*.mdx"],
        )
    )
    outcome = await process_job(job, client=client)
    assert outcome.docs_total == 2
    assert outcome.docs_processed == 2
    assert outcome.docs_failed == 0
    assert client.ingested  # FakeRagEmbeddingClient recorded the batch
    # JSONL artifact has one line per doc
    lines = [line for line in outcome.artifact_jsonl.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert {p["title"] for p in parsed} == {"Middleware", "Getting Started"}


@pytest.mark.asyncio
async def test_process_job_openapi_uses_local_fetch(
    monkeypatch: pytest.MonkeyPatch, petstore_spec: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        openapi_source,
        "fetch_and_resolve",
        lambda url, **_: openapi_source.OpenapiSource(
            spec=openapi_source.resolve_internal_refs(petstore_spec), raw_url=url
        ),
    )
    client = FakeRagEmbeddingClient()
    job = _make_job(
        JobSource(
            type="openapi",
            url="https://example.invalid",
            openapi_url="https://example.invalid/spec.json",
        )
    )
    outcome = await process_job(job, client=client)
    assert outcome.docs_total == 3  # GET/POST /pets + GET /pets/{petId}
    assert all(d.doc_type == "openapi_endpoint" for d in outcome.documents)


@pytest.mark.asyncio
async def test_process_job_unknown_source_raises() -> None:
    client = FakeRagEmbeddingClient()
    job = _make_job(JobSource(type="local_path", url="/tmp/x"))
    with pytest.raises(NotImplementedError):
        await process_job(job, client=client)


def test_batch_size_constant() -> None:
    assert BATCH_SIZE == 50
