"""Packer unit tests use ``CharTokenizer`` so they're deterministic and don't
depend on tiktoken's BPE download."""

from __future__ import annotations

from doc_search_mcp.packer import (
    CharTokenizer,
    PackedChunk,
    PackResult,
    pack,
)
from doc_search_shared.clients.rag_search_client import SearchHit


def _hit(
    *,
    chunk_id: str,
    score: float,
    content: str,
    section_id: str | None = None,
    title: str = "T",
) -> SearchHit:
    return SearchHit(
        document_id=f"doc-{chunk_id}",
        chunk_id=chunk_id,
        library_id="/vercel/next.js",
        version="v15.1.0",
        source_url=f"https://example.invalid/{chunk_id}",
        title=title,
        breadcrumbs=["Docs"],
        content=content,
        score=score,
        section_id=section_id,
    )


# Char ratio = 4 → 800 chars ≈ 200 tokens, 4000 chars ≈ 1000 tokens.
TOKENIZER = CharTokenizer(ratio=4)


def _content_of_tokens(n: int, char: str = "x") -> str:
    return char * (n * 4)


def test_pack_empty_returns_empty() -> None:
    result = pack([], token_budget=100, tokenizer=TOKENIZER)
    assert result == PackResult()


def test_top_chunk_always_included_truncated_when_oversized() -> None:
    # Phase 5 acceptance: budget=200 vs single 5000-token chunk.
    big = _hit(chunk_id="big", score=1.0, content=_content_of_tokens(5000))
    result = pack([big], token_budget=200, tokenizer=TOKENIZER)
    assert result.truncated is True
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.truncated is True
    # Headroom floor of 200 → truncated chunk capped at exactly 200 tokens.
    assert chunk.tokens == 200
    assert result.tokens_used == 200


def test_budget_2000_with_oversized_corpus_returns_near_budget() -> None:
    hits = [
        _hit(chunk_id=f"c{i}", score=1.0 - 0.01 * i, content=_content_of_tokens(800))
        for i in range(10)
    ]
    result = pack(hits, token_budget=2000, tokenizer=TOKENIZER)
    # Greedy with keep-scanning fits 2 x 800-token chunks plus the top, but
    # the *first* chunk also costs 800, so total is 2 x 800 = 1600.
    assert result.tokens_used <= 2000
    assert result.tokens_used >= 1600
    assert result.truncated is True


def test_dedupe_by_section_id_drops_duplicates() -> None:
    hits = [
        _hit(chunk_id="a", score=1.0, content=_content_of_tokens(50), section_id="auth"),
        _hit(chunk_id="b", score=0.9, content=_content_of_tokens(50), section_id="auth"),
        _hit(chunk_id="c", score=0.8, content=_content_of_tokens(50), section_id="routing"),
    ]
    result = pack(hits, token_budget=10_000, tokenizer=TOKENIZER)
    chunk_ids = [c.chunk_id for c in result.chunks]
    assert chunk_ids == ["a", "c"]


def test_keep_scanning_after_overflow() -> None:
    hits = [
        _hit(chunk_id="top", score=1.0, content=_content_of_tokens(100)),
        _hit(chunk_id="huge", score=0.9, content=_content_of_tokens(5000)),
        _hit(chunk_id="small", score=0.8, content=_content_of_tokens(100)),
    ]
    result = pack(hits, token_budget=300, tokenizer=TOKENIZER)
    chunk_ids = [c.chunk_id for c in result.chunks]
    assert chunk_ids == ["top", "small"]
    assert result.truncated is True


def test_include_examples_false_strips_code_fences() -> None:
    body = "Intro paragraph.\n\n```python\nprint('hi')\n```\n\nMore prose."
    hits = [_hit(chunk_id="c", score=1.0, content=body)]
    result = pack(
        hits,
        token_budget=10_000,
        tokenizer=TOKENIZER,
        include_examples=False,
    )
    assert "```" not in result.chunks[0].content
    assert "print('hi')" not in result.chunks[0].content
    assert "Intro paragraph." in result.chunks[0].content


def test_include_examples_false_does_not_force_truncation() -> None:
    body = "short prose " + "```\n" + ("xxxx " * 5000) + "\n```"
    hits = [_hit(chunk_id="c", score=1.0, content=body)]
    result = pack(
        hits,
        token_budget=200,
        tokenizer=TOKENIZER,
        include_examples=False,
    )
    # Without code, content is short → fits in budget; truncated=False.
    assert result.truncated is False
    assert result.chunks[0].truncated is False


def test_pack_orders_by_score() -> None:
    hits = [
        _hit(chunk_id="low", score=0.1, content="small"),
        _hit(chunk_id="hi", score=0.9, content="medium"),
        _hit(chunk_id="mid", score=0.5, content="larger content"),
    ]
    result = pack(hits, token_budget=10_000, tokenizer=TOKENIZER)
    chunk_ids = [c.chunk_id for c in result.chunks]
    assert chunk_ids[0] == "hi"
    assert set(chunk_ids) == {"hi", "mid", "low"}


def test_packed_chunk_carries_metadata() -> None:
    hit = _hit(chunk_id="c", score=0.8, content="hello", title="Routing")
    [chunk] = pack([hit], token_budget=10, tokenizer=TOKENIZER).chunks
    assert isinstance(chunk, PackedChunk)
    assert chunk.title == "Routing"
    assert chunk.source_url.endswith("/c")
    assert chunk.breadcrumbs == ["Docs"]
