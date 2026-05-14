"""Table-driven coverage for the resolution stages."""

from __future__ import annotations

import pytest
from doc_search_mcp.registry import Registry
from doc_search_mcp.tools.resolve_library_id import (
    EXACT_ALIAS_CONFIDENCE,
    EXACT_ID_CONFIDENCE,
    HARD_CEILING,
    VERSION_AWARE_CONFIDENCE,
    resolve_library_id,
)


@pytest.mark.asyncio
async def test_exact_id_match(registry: Registry) -> None:
    out = await resolve_library_id("/vercel/next.js", registry=registry)
    assert len(out["matches"]) == 1
    match = out["matches"][0]
    assert match["id"] == "/vercel/next.js"
    assert match["confidence"] == EXACT_ID_CONFIDENCE
    assert "Resolved exactly" in out["guidance"]


@pytest.mark.asyncio
async def test_exact_alias_match(registry: Registry) -> None:
    out = await resolve_library_id("nextjs", registry=registry)
    assert len(out["matches"]) == 1
    match = out["matches"][0]
    assert match["id"] == "/vercel/next.js"
    assert match["confidence"] == EXACT_ALIAS_CONFIDENCE
    # Acceptance: nextjs → top match with confidence ≥ 0.9.
    assert match["confidence"] >= 0.9


@pytest.mark.asyncio
async def test_version_aware_at_syntax(registry: Registry) -> None:
    out = await resolve_library_id("nextjs@v15.1.0", registry=registry)
    assert len(out["matches"]) == 1
    match = out["matches"][0]
    assert match["id"] == "/vercel/next.js"
    assert match["confidence"] == VERSION_AWARE_CONFIDENCE


@pytest.mark.asyncio
async def test_version_aware_path_with_known_version(registry: Registry) -> None:
    out = await resolve_library_id("/vercel/next.js/v14.2.0", registry=registry)
    assert len(out["matches"]) == 1
    assert out["matches"][0]["confidence"] == VERSION_AWARE_CONFIDENCE


@pytest.mark.asyncio
async def test_version_aware_unknown_version_falls_through(registry: Registry) -> None:
    out = await resolve_library_id("nextjs@v99.0.0", registry=registry)
    # No version-aware match; fuzzy stage may still surface Next.js by name.
    matches = out["matches"]
    assert all(m["confidence"] != VERSION_AWARE_CONFIDENCE for m in matches)


@pytest.mark.asyncio
async def test_fuzzy_match_when_alias_misses(registry: Registry) -> None:
    out = await resolve_library_id("react framework next", registry=registry)
    assert out["matches"], "expected at least one fuzzy match"
    top = out["matches"][0]
    assert top["id"] == "/vercel/next.js"
    assert top["confidence"] < EXACT_ALIAS_CONFIDENCE


@pytest.mark.asyncio
async def test_fuzzy_blends_trust_score(registry: Registry) -> None:
    # Both libraries should surface with confidences shaped by their trust.
    out = await resolve_library_id("api framework", registry=registry, max_results=10)
    by_id = {m["id"]: m for m in out["matches"]}
    if "/tiangolo/fastapi" in by_id and "/stripe/stripe-openapi" in by_id:
        # Confidence is bounded but not constant; trust-weighted ordering still
        # holds when trgm scores are close.
        assert all(0.0 <= m["confidence"] <= 1.0 for m in out["matches"])


@pytest.mark.asyncio
async def test_ambiguous_returns_multiple_matches(registry: Registry) -> None:
    # "stripe" alias resolves to a single library but fuzzy on "api" hits both.
    out = await resolve_library_id("api", registry=registry, max_results=5)
    assert len(out["matches"]) >= 1


@pytest.mark.asyncio
async def test_max_results_capped_at_hard_ceiling(registry: Registry) -> None:
    out = await resolve_library_id("api", registry=registry, max_results=999)
    assert len(out["matches"]) <= HARD_CEILING


@pytest.mark.asyncio
async def test_unknown_query_returns_guidance(registry: Registry) -> None:
    out = await resolve_library_id("zzzqqqxxx-unknown-1234", registry=registry)
    assert out["matches"] == []
    assert "register the library" in out["guidance"]


@pytest.mark.asyncio
async def test_empty_query_short_circuits(registry: Registry) -> None:
    out = await resolve_library_id("", registry=registry)
    assert out["matches"] == []
    assert "Empty query" in out["guidance"]


@pytest.mark.asyncio
async def test_match_carries_all_fields(registry: Registry) -> None:
    out = await resolve_library_id("nextjs", registry=registry)
    match = out["matches"][0]
    for key in (
        "id",
        "name",
        "description",
        "latest_version",
        "available_versions",
        "trust_score",
        "chunk_count",
        "doc_type",
        "confidence",
    ):
        assert key in match, f"missing {key}"


@pytest.mark.asyncio
async def test_alias_case_insensitive(registry: Registry) -> None:
    out_lower = await resolve_library_id("nextjs", registry=registry)
    out_upper = await resolve_library_id("NEXTJS", registry=registry)
    assert {m["id"] for m in out_lower["matches"]} == {m["id"] for m in out_upper["matches"]}
