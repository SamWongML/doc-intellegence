"""MCP → RAG hybrid-search handoff.

The ``RagSearchClient`` Protocol is the wiring contract. Signatures here MUST
NOT change once services depend on them.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from ..logging import get_logger

log = get_logger(__name__)


class SearchHit(BaseModel):
    document_id: str
    chunk_id: str
    library_id: str
    version: str | None = None
    source_url: str
    title: str
    breadcrumbs: list[str]
    content: str
    score: float
    section_id: str | None = None


@runtime_checkable
class RagSearchClient(Protocol):
    async def hybrid_search(
        self,
        query: str,
        *,
        library_id: str,
        version: str | None = None,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]: ...


class FakeRagSearchClient:
    """Dev/test stub. Returns canned hits; does not network.

    TODO[wiring]: Replace with the real httpx-based client that calls the RAG
    hybrid-search endpoint. Only edit this file when wiring.
    """

    def __init__(self, fixtures: list[SearchHit] | None = None) -> None:
        self._fixtures = fixtures or []

    async def hybrid_search(
        self,
        query: str,
        *,
        library_id: str,
        version: str | None = None,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        log.info(
            "fake.hybrid_search",
            query=query,
            library_id=library_id,
            version=version,
            top_k=top_k,
        )
        if self._fixtures:
            return self._fixtures[:top_k]
        # Deterministic single fake hit so callers can exercise the shape.
        return [
            SearchHit(
                document_id="fake-doc-1",
                chunk_id="fake-chunk-1",
                library_id=library_id,
                version=version,
                source_url=f"https://example.invalid{library_id}/page",
                title=f"Fake result for {query!r}",
                breadcrumbs=["Fakes", "Search"],
                content=f"Fake hit body for query: {query}",
                score=0.42,
                section_id=None,
            )
        ][:top_k]


__all__ = ["FakeRagSearchClient", "RagSearchClient", "SearchHit"]
