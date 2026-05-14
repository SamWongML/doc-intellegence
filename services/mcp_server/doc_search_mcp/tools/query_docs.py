"""``query_docs`` tool: hybrid-search a library, pack into a token budget."""

from __future__ import annotations

from typing import Any

from doc_search_shared.clients.rag_search_client import RagSearchClient
from doc_search_shared.logging import get_logger
from pydantic import BaseModel, Field

from ..packer import PackResult, Tokenizer, pack
from ..registry import Registry

log = get_logger(__name__)

DEFAULT_TOP_K = 20


class QueryDocsResponse(BaseModel):
    library_id: str
    version: str | None = None
    topic: str
    token_budget: int
    tokens_used: int = 0
    truncated: bool = False
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    guidance: str | None = None


def _missing_library_response(library_id: str, topic: str, token_budget: int) -> dict[str, Any]:
    return QueryDocsResponse(
        library_id=library_id,
        topic=topic,
        token_budget=token_budget,
        error=f"Unknown library_id: {library_id!r}",
        guidance=(
            "Call resolve_library_id with the human-readable name (e.g. 'next.js') "
            "to find the canonical id, then retry."
        ),
    ).model_dump()


def _result_to_response(
    result: PackResult,
    *,
    library_id: str,
    version: str | None,
    topic: str,
    token_budget: int,
) -> dict[str, Any]:
    return QueryDocsResponse(
        library_id=library_id,
        version=version,
        topic=topic,
        token_budget=token_budget,
        tokens_used=result.tokens_used,
        truncated=result.truncated,
        chunks=[c.model_dump() for c in result.chunks],
    ).model_dump()


async def query_docs(
    library_id: str,
    topic: str,
    *,
    registry: Registry,
    search: RagSearchClient,
    token_budget: int = 6000,
    version: str | None = None,
    include_examples: bool = True,
    top_k: int = DEFAULT_TOP_K,
    tokenizer: Tokenizer | None = None,
) -> dict[str, Any]:
    """Run hybrid search for ``topic`` over ``library_id`` and pack the results."""
    record = await registry.get_library(library_id)
    if record is None:
        log.info("query_docs.unknown_library", library_id=library_id)
        return _missing_library_response(library_id, topic, token_budget)

    if version and not await registry.has_version(library_id, version):
        log.info(
            "query_docs.unknown_version",
            library_id=library_id,
            version=version,
        )
        return QueryDocsResponse(
            library_id=library_id,
            version=version,
            topic=topic,
            token_budget=token_budget,
            error=f"Unknown version {version!r} for {library_id}",
            guidance=(
                f"Available versions for {library_id}: "
                f"{', '.join(record.available_versions) or 'none'}."
            ),
        ).model_dump()

    hits = await search.hybrid_search(
        topic,
        library_id=library_id,
        version=version,
        top_k=top_k,
    )
    log.info(
        "query_docs.hits",
        library_id=library_id,
        version=version,
        topic=topic,
        count=len(hits),
    )
    result = pack(
        hits,
        token_budget=token_budget,
        include_examples=include_examples,
        tokenizer=tokenizer,
    )
    return _result_to_response(
        result,
        library_id=library_id,
        version=version,
        topic=topic,
        token_budget=token_budget,
    )


__all__ = ["QueryDocsResponse", "query_docs"]
