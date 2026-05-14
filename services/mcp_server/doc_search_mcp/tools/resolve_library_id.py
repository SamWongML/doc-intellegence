"""``resolve_library_id`` tool.

Resolution order (per Phase 5 spec):

1. Exact ``library_id`` match (path-shaped query).
2. Exact alias (case-insensitive).
3. Version-aware parse (``query@version``, ``query/version``, or
   ``library_id`` whose tail segment is a known version).
4. ``pg_trgm`` fuzzy on ``name`` + ``description``.

The first stage that yields any matches wins; remaining stages are skipped.
Confidence scores follow the policy from `phase-5.md`:

* exact ID → 1.0
* exact alias → 0.95
* version-aware → 0.90
* fuzzy → ``0.7 * trgm_similarity + 0.3 * trust_score``

The response is capped at ``min(max_results, 10)``.
"""

from __future__ import annotations

import re
from typing import Any

from doc_search_shared.ids import parse_library_id
from doc_search_shared.logging import get_logger
from pydantic import BaseModel, Field

from ..registry import LibraryRecord, Registry

log = get_logger(__name__)

HARD_CEILING = 10
EXACT_ID_CONFIDENCE = 1.0
EXACT_ALIAS_CONFIDENCE = 0.95
VERSION_AWARE_CONFIDENCE = 0.90
FUZZY_TRGM_WEIGHT = 0.7
FUZZY_TRUST_WEIGHT = 0.3

# Strip leading ``/`` and accept ``foo@1.2`` or ``foo/1.2`` (when ``foo`` does
# NOT itself look like a /org/project library id).
_AT_VERSION_RE = re.compile(r"^(?P<base>[^@]+?)@(?P<version>[A-Za-z0-9._-]+)$")


class Match(BaseModel):
    id: str
    name: str
    description: str | None = None
    latest_version: str | None = None
    available_versions: list[str] = Field(default_factory=list)
    trust_score: float
    chunk_count: int
    doc_type: str | None = None
    confidence: float

    @classmethod
    def from_record(cls, record: LibraryRecord, *, confidence: float) -> Match:
        return cls(
            id=record.id,
            name=record.name,
            description=record.description,
            latest_version=record.latest_version,
            available_versions=list(record.available_versions),
            trust_score=record.trust_score,
            chunk_count=record.chunk_count,
            doc_type=record.doc_type,
            confidence=round(confidence, 4),
        )


class ResolveResponse(BaseModel):
    query: str
    matches: list[Match] = Field(default_factory=list)
    guidance: str


def _looks_like_library_id(query: str) -> bool:
    return query.startswith("/") and query.count("/") >= 2


def _split_versioned(query: str) -> tuple[str, str | None]:
    """Return ``(base, version)`` if the query carries an explicit version."""
    m = _AT_VERSION_RE.match(query)
    if m:
        return m.group("base"), m.group("version")
    return query, None


async def _exact_id(registry: Registry, query: str) -> list[Match]:
    if not _looks_like_library_id(query):
        return []
    try:
        parse_library_id(query)
    except ValueError:
        return []
    record = await registry.get_library(query)
    if record is None:
        return []
    return [Match.from_record(record, confidence=EXACT_ID_CONFIDENCE)]


async def _exact_alias(registry: Registry, query: str) -> list[Match]:
    records = await registry.find_by_alias(query)
    return [Match.from_record(r, confidence=EXACT_ALIAS_CONFIDENCE) for r in records]


async def _version_aware(registry: Registry, query: str) -> list[Match]:
    base, version = _split_versioned(query)
    if version is None:
        # Fallback: a path-shaped query whose third segment IS a registered version.
        if _looks_like_library_id(query):
            try:
                ref = parse_library_id(query)
            except ValueError:
                return []
            if ref.version:
                base_id = f"/{ref.org}/{ref.project}"
                base_record = await registry.get_library(base_id)
                if base_record and ref.version in base_record.available_versions:
                    return [Match.from_record(base_record, confidence=VERSION_AWARE_CONFIDENCE)]
        return []

    candidates: list[LibraryRecord] = []
    if _looks_like_library_id(base):
        record = await registry.get_library(base)
        if record:
            candidates.append(record)
    if not candidates:
        candidates.extend(await registry.find_by_alias(base))

    out: list[Match] = []
    for record in candidates:
        if version in record.available_versions or version == record.latest_version:
            out.append(Match.from_record(record, confidence=VERSION_AWARE_CONFIDENCE))
    return out


async def _fuzzy(registry: Registry, query: str, *, limit: int) -> list[Match]:
    fuzzy = await registry.fuzzy_search(query, limit=limit)
    out: list[Match] = []
    for fm in fuzzy:
        confidence = (
            FUZZY_TRGM_WEIGHT * fm.trgm_similarity + FUZZY_TRUST_WEIGHT * fm.library.trust_score
        )
        out.append(Match.from_record(fm.library, confidence=confidence))
    out.sort(key=lambda m: m.confidence, reverse=True)
    return out


def _guidance(stage: str, matches: list[Match]) -> str:
    if not matches:
        return (
            "No libraries matched. Try a different name, the project's GitHub org, "
            "or register the library via the ingest API."
        )
    top = matches[0]
    if stage == "exact_id":
        return f"Resolved exactly: {top.id}. Pass this id straight to query_docs."
    if stage == "exact_alias":
        return (
            f"Matched by alias to {top.id} (confidence {top.confidence:.2f}). "
            "Use this id with query_docs."
        )
    if stage == "version_aware":
        return (
            f"Resolved to {top.id} with version-aware parsing. "
            "Pass library_id + version to query_docs."
        )
    return (
        f"Best fuzzy match: {top.id} (confidence {top.confidence:.2f}). "
        "Confirm before calling query_docs; refine the query if it looks wrong."
    )


async def resolve_library_id(
    query: str,
    *,
    registry: Registry,
    max_results: int = 5,
) -> dict[str, Any]:
    """Resolve a free-form library name to one or more registered library IDs."""
    if not query or not query.strip():
        return ResolveResponse(
            query=query,
            matches=[],
            guidance="Empty query. Provide a library name, alias, or /org/project id.",
        ).model_dump()

    cap = min(max(1, max_results), HARD_CEILING)
    query = query.strip()

    stages: list[tuple[str, list[Match]]] = []

    exact_matches = await _exact_id(registry, query)
    stages.append(("exact_id", exact_matches))
    if not exact_matches:
        alias_matches = await _exact_alias(registry, query)
        stages.append(("exact_alias", alias_matches))
        if not alias_matches:
            version_matches = await _version_aware(registry, query)
            stages.append(("version_aware", version_matches))
            if not version_matches:
                fuzzy_matches = await _fuzzy(registry, query, limit=cap)
                stages.append(("fuzzy", fuzzy_matches))

    stage, matches = next(((s, m) for s, m in stages if m), (stages[-1][0], []))
    matches = matches[:cap]

    log.info(
        "resolve_library_id",
        query=query,
        stage=stage,
        match_count=len(matches),
    )
    return ResolveResponse(
        query=query,
        matches=matches,
        guidance=_guidance(stage, matches),
    ).model_dump()


__all__ = ["Match", "ResolveResponse", "resolve_library_id"]
