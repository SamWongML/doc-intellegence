"""``query_docs`` integration tests against ``FakeRagSearchClient``.

The tokenizer is the deterministic ``CharTokenizer`` (no tiktoken download)
and the search client returns canned hits — both substitutions match the
Phase 5 acceptance plan ("integration tests use FakeRagSearchClient with known
fixtures")."""

from __future__ import annotations

import pytest
from doc_search_mcp.packer import CharTokenizer
from doc_search_mcp.registry import Registry
from doc_search_mcp.tools.query_docs import query_docs
from doc_search_shared.clients.rag_search_client import (
    FakeRagSearchClient,
    SearchHit,
)

TOKENIZER = CharTokenizer(ratio=4)


def _hit(
    chunk_id: str,
    *,
    score: float,
    content: str,
    section_id: str | None = None,
    library_id: str = "/vercel/next.js",
    version: str | None = "v15.1.0",
) -> SearchHit:
    return SearchHit(
        document_id=f"doc-{chunk_id}",
        chunk_id=chunk_id,
        library_id=library_id,
        version=version,
        source_url=f"https://example.invalid/{chunk_id}",
        title=f"Title {chunk_id}",
        breadcrumbs=["Docs"],
        content=content,
        score=score,
        section_id=section_id,
    )


def _content(tokens: int) -> str:
    return "x" * (tokens * 4)


@pytest.mark.asyncio
async def test_unknown_library_returns_guidance(registry: Registry) -> None:
    out = await query_docs(
        "/no/such",
        "auth",
        registry=registry,
        search=FakeRagSearchClient(),
        token_budget=1000,
        tokenizer=TOKENIZER,
    )
    assert out["error"]
    assert "resolve_library_id" in out["guidance"]
    assert out["chunks"] == []


@pytest.mark.asyncio
async def test_unknown_version_returns_guidance(registry: Registry) -> None:
    out = await query_docs(
        "/vercel/next.js",
        "auth",
        registry=registry,
        search=FakeRagSearchClient(),
        version="v0.0.0",
        token_budget=1000,
        tokenizer=TOKENIZER,
    )
    assert out["error"]
    assert "Available versions" in out["guidance"]


@pytest.mark.asyncio
async def test_budget_2000_returns_under_budget(registry: Registry) -> None:
    hits = [_hit(f"c{i}", score=1.0 - 0.01 * i, content=_content(800)) for i in range(10)]
    search = FakeRagSearchClient(fixtures=hits)
    out = await query_docs(
        "/vercel/next.js",
        "middleware",
        registry=registry,
        search=search,
        token_budget=2000,
        tokenizer=TOKENIZER,
    )
    assert out["tokens_used"] <= 2000
    assert out["tokens_used"] >= 1600
    assert out["truncated"] is True


@pytest.mark.asyncio
async def test_budget_200_truncates_top_chunk(registry: Registry) -> None:
    hits = [_hit("big", score=1.0, content=_content(5000))]
    search = FakeRagSearchClient(fixtures=hits)
    out = await query_docs(
        "/vercel/next.js",
        "middleware",
        registry=registry,
        search=search,
        token_budget=200,
        tokenizer=TOKENIZER,
    )
    assert out["truncated"] is True
    assert len(out["chunks"]) == 1
    assert out["chunks"][0]["truncated"] is True


@pytest.mark.asyncio
async def test_include_examples_false_strips_code(registry: Registry) -> None:
    body = "Setup steps.\n\n```bash\nnpm install next\n```\n\nThen run."
    hits = [_hit("c1", score=1.0, content=body)]
    search = FakeRagSearchClient(fixtures=hits)
    out = await query_docs(
        "/vercel/next.js",
        "install",
        registry=registry,
        search=search,
        token_budget=10_000,
        include_examples=False,
        tokenizer=TOKENIZER,
    )
    assert "```" not in out["chunks"][0]["content"]
    assert "npm install" not in out["chunks"][0]["content"]


@pytest.mark.asyncio
async def test_dedupe_by_section_id(registry: Registry) -> None:
    hits = [
        _hit("a", score=1.0, content=_content(50), section_id="auth"),
        _hit("b", score=0.9, content=_content(50), section_id="auth"),
        _hit("c", score=0.8, content=_content(50), section_id="routing"),
    ]
    search = FakeRagSearchClient(fixtures=hits)
    out = await query_docs(
        "/vercel/next.js",
        "auth",
        registry=registry,
        search=search,
        token_budget=10_000,
        tokenizer=TOKENIZER,
    )
    chunk_ids = [c["chunk_id"] for c in out["chunks"]]
    assert chunk_ids == ["a", "c"]


@pytest.mark.asyncio
async def test_versioned_call_passes_version_to_search(registry: Registry) -> None:
    captured: dict[str, object] = {}

    class CapturingSearch:
        async def hybrid_search(
            self,
            query: str,
            *,
            library_id: str,
            version: str | None = None,
            top_k: int = 20,
            filters: dict[str, object] | None = None,
        ) -> list[SearchHit]:
            captured["query"] = query
            captured["library_id"] = library_id
            captured["version"] = version
            captured["top_k"] = top_k
            return [_hit("c", score=1.0, content="ok")]

    out = await query_docs(
        "/vercel/next.js",
        "topic",
        registry=registry,
        search=CapturingSearch(),
        version="v14.2.0",
        token_budget=1000,
        tokenizer=TOKENIZER,
    )
    assert captured == {
        "query": "topic",
        "library_id": "/vercel/next.js",
        "version": "v14.2.0",
        "top_k": 20,
    }
    assert out["version"] == "v14.2.0"
