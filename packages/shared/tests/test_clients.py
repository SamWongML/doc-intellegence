"""Placeholder RAG clients satisfy their Protocols and return realistic fakes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from doc_search_shared.clients import (
    FakeRagEmbeddingClient,
    FakeRagSearchClient,
    IngestResult,
    RagEmbeddingClient,
    RagSearchClient,
    SearchHit,
)
from doc_search_shared.models import ProcessedDocument


def _doc(idx: int) -> ProcessedDocument:
    return ProcessedDocument(
        document_id=f"doc-{idx}",
        library_id="/vercel/next.js",
        version="v15.1.0",
        source_url=f"https://example.invalid/{idx}",
        title=f"Doc {idx}",
        doc_type="guide",
        markdown=f"# Doc {idx}",
        content_hash=f"hash-{idx}",
        extracted_at=datetime(2026, 5, 14, tzinfo=UTC),
    )


def test_fake_embedding_client_protocol() -> None:
    client = FakeRagEmbeddingClient()
    assert isinstance(client, RagEmbeddingClient)


def test_fake_search_client_protocol() -> None:
    client = FakeRagSearchClient()
    assert isinstance(client, RagSearchClient)


@pytest.mark.asyncio
async def test_fake_embedding_ingest_returns_realistic_shape() -> None:
    client = FakeRagEmbeddingClient()
    result = await client.ingest_documents(
        [_doc(1), _doc(2)],
        library_id="/vercel/next.js",
        version="v15.1.0",
    )
    assert isinstance(result, IngestResult)
    assert result.ingested == 2
    assert result.failed == 0
    assert result.document_ids == ["doc-1", "doc-2"]
    assert result.chunk_count > 0


@pytest.mark.asyncio
async def test_fake_embedding_tombstone_tracks_ids() -> None:
    client = FakeRagEmbeddingClient()
    await client.tombstone_documents(
        ["doc-1", "doc-2"],
        library_id="/vercel/next.js",
        version="v15.1.0",
    )
    assert client.tombstoned == ["doc-1", "doc-2"]


@pytest.mark.asyncio
async def test_fake_search_default_hit() -> None:
    client = FakeRagSearchClient()
    hits = await client.hybrid_search(
        "middleware",
        library_id="/vercel/next.js",
        version="v15.1.0",
    )
    assert len(hits) == 1
    assert hits[0].library_id == "/vercel/next.js"


@pytest.mark.asyncio
async def test_fake_search_returns_fixtures() -> None:
    fixture = SearchHit(
        document_id="d1",
        chunk_id="c1",
        library_id="/a/b",
        version=None,
        source_url="https://x",
        title="t",
        breadcrumbs=["a", "b"],
        content="hello",
        score=0.9,
        section_id=None,
    )
    client = FakeRagSearchClient(fixtures=[fixture])
    hits = await client.hybrid_search("q", library_id="/a/b", top_k=5)
    assert hits == [fixture]
