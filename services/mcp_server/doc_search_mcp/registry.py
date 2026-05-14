"""Registry queries used by both MCP tools.

The :class:`Registry` Protocol is the read-side interface against the
``libraries`` / ``library_aliases`` / ``library_versions`` tables. Two
implementations ship:

* :class:`PgRegistry` — async psycopg pool with a two-layer cache: in-process
  LRU (10 min TTL) over Redis (5 min TTL). Production wiring.
* :class:`MemoryRegistry` — pure Python dict backend used by tests and the
  ``stdio`` smoke runner.

The cache lives on top of a backend so the same caching policy applies to
both implementations should we ever wrap the in-memory variant.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from doc_search_shared.logging import get_logger
from pydantic import BaseModel, Field

log = get_logger(__name__)


# --- Records ------------------------------------------------------------------


class LibraryRecord(BaseModel):
    """Read model for a single library row + denormalised version list."""

    id: str
    name: str
    description: str | None = None
    homepage_url: str | None = None
    doc_type: str | None = None
    latest_version: str | None = None
    trust_score: float = 0.5
    chunk_count: int = 0
    available_versions: list[str] = Field(default_factory=list)


class FuzzyMatch(BaseModel):
    library: LibraryRecord
    trgm_similarity: float


# --- Backend protocol ---------------------------------------------------------


@runtime_checkable
class RegistryBackend(Protocol):
    async def get_library(self, library_id: str) -> LibraryRecord | None: ...
    async def find_by_alias(self, alias: str) -> list[LibraryRecord]: ...
    async def fuzzy_search(self, query: str, *, limit: int) -> list[FuzzyMatch]: ...
    async def has_version(self, library_id: str, version: str) -> bool: ...


# --- Two-layer cache ----------------------------------------------------------


class _LRUCacheTTL:
    """Tiny in-process LRU + TTL cache. Not threadsafe; one instance per process."""

    def __init__(self, *, max_size: int = 1024, ttl_seconds: int = 600) -> None:
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: str) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


class TwoLayerCache:
    """LRU (long TTL) → Redis (short TTL) → loader.

    The in-process LRU absorbs hot-path repeats for a single replica; Redis
    shares cross-replica state but has the shorter TTL so invalidations
    propagate within a few minutes.
    """

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        ttl_inproc: int = 600,
        ttl_redis: int = 300,
        max_inproc_size: int = 1024,
        namespace: str = "mcp:registry",
    ) -> None:
        self._lru = _LRUCacheTTL(max_size=max_inproc_size, ttl_seconds=ttl_inproc)
        self._redis = redis_client
        self._ttl_redis = ttl_redis
        self._ns = namespace

    def _redis_key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        cached = self._lru.get(key)
        if cached is not None:
            return json.loads(cached)

        if self._redis is not None:
            try:
                raw = await self._redis.get(self._redis_key(key))
            except Exception as exc:  # pragma: no cover - redis transient
                log.warning("registry.cache.redis_get_failed", key=key, error=str(exc))
                raw = None
            if raw is not None:
                self._lru.set(key, raw if isinstance(raw, str) else raw.decode("utf-8"))
                return json.loads(raw)

        value = await loader()
        encoded = json.dumps(value, default=str)
        self._lru.set(key, encoded)
        if self._redis is not None:
            try:
                await self._redis.set(
                    self._redis_key(key),
                    encoded,
                    ex=self._ttl_redis,
                )
            except Exception as exc:  # pragma: no cover - redis transient
                log.warning("registry.cache.redis_set_failed", key=key, error=str(exc))
        return value

    def invalidate_all(self) -> None:
        self._lru.clear()


# --- Cached registry façade ---------------------------------------------------


class Registry:
    """Caching wrapper over a :class:`RegistryBackend`.

    Both MCP tools share one instance via FastMCP lifespan state. Cache keys
    are deliberately simple — the registry is small and reads dominate writes.
    """

    def __init__(
        self,
        backend: RegistryBackend,
        *,
        cache: TwoLayerCache | None = None,
    ) -> None:
        self._backend = backend
        self._cache = cache or TwoLayerCache()

    async def get_library(self, library_id: str) -> LibraryRecord | None:
        async def _load() -> dict[str, Any] | None:
            row = await self._backend.get_library(library_id)
            return row.model_dump() if row else None

        data = await self._cache.get_or_load(f"lib:{library_id}", _load)
        return LibraryRecord.model_validate(data) if data else None

    async def find_by_alias(self, alias: str) -> list[LibraryRecord]:
        async def _load() -> list[dict[str, Any]]:
            rows = await self._backend.find_by_alias(alias)
            return [r.model_dump() for r in rows]

        data = await self._cache.get_or_load(f"alias:{alias.lower()}", _load)
        return [LibraryRecord.model_validate(d) for d in data]

    async def fuzzy_search(self, query: str, *, limit: int = 10) -> list[FuzzyMatch]:
        # Fuzzy results are intentionally not cached — query strings are
        # high-cardinality and the trgm index handles them quickly.
        return await self._backend.fuzzy_search(query, limit=limit)

    async def has_version(self, library_id: str, version: str) -> bool:
        return await self._backend.has_version(library_id, version)


# --- Memory backend (tests + dev) --------------------------------------------


class MemoryBackend:
    """In-process backend for tests, the seed runner, and offline dev."""

    def __init__(
        self,
        libraries: list[LibraryRecord],
        *,
        aliases: dict[str, list[str]] | None = None,
    ) -> None:
        self._libs: dict[str, LibraryRecord] = {lib.id: lib for lib in libraries}
        # alias (lowercased) -> [library_id, ...]
        self._aliases: dict[str, list[str]] = {
            k.lower(): list(v) for k, v in (aliases or {}).items()
        }

    async def get_library(self, library_id: str) -> LibraryRecord | None:
        return self._libs.get(library_id)

    async def find_by_alias(self, alias: str) -> list[LibraryRecord]:
        ids = self._aliases.get(alias.lower(), [])
        return [self._libs[i] for i in ids if i in self._libs]

    async def fuzzy_search(self, query: str, *, limit: int) -> list[FuzzyMatch]:
        # Trivial trigram-ish similarity used only in tests. Production uses
        # Postgres pg_trgm via :class:`PgBackend`.
        q = query.lower()
        results: list[FuzzyMatch] = []
        for lib in self._libs.values():
            haystack = " ".join(filter(None, [lib.name, lib.description or ""])).lower()
            sim = _crude_similarity(q, haystack)
            if sim > 0:
                results.append(FuzzyMatch(library=lib, trgm_similarity=sim))
        results.sort(key=lambda m: m.trgm_similarity, reverse=True)
        return results[:limit]

    async def has_version(self, library_id: str, version: str) -> bool:
        lib = self._libs.get(library_id)
        if lib is None:
            return False
        return version in lib.available_versions or version == lib.latest_version


def _crude_similarity(query: str, text: str) -> float:
    """Approximation good enough for tests; mirrors trigram intuition."""
    if not query or not text:
        return 0.0
    qg = _trigrams(query)
    tg = _trigrams(text)
    if not qg or not tg:
        return 0.0
    return len(qg & tg) / len(qg | tg)


def _trigrams(text: str) -> set[str]:
    padded = f"  {text}  "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


# --- Postgres backend ---------------------------------------------------------


class PgBackend:
    """Async psycopg backend.

    Lazy-imports ``psycopg`` so tests can avoid the dependency. Connections
    come from a long-lived ``AsyncConnectionPool`` set up in the FastMCP
    lifespan.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def get_library(self, library_id: str) -> LibraryRecord | None:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT id, name, description, homepage_url, doc_type,
                           latest_version, trust_score, chunk_count
                    FROM libraries WHERE id = %s
                    """,
                (library_id,),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            versions = await _list_versions(cur, library_id)
        return _row_to_library(row, versions)

    async def find_by_alias(self, alias: str) -> list[LibraryRecord]:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT l.id, l.name, l.description, l.homepage_url, l.doc_type,
                           l.latest_version, l.trust_score, l.chunk_count
                    FROM libraries l
                    JOIN library_aliases a ON a.library_id = l.id
                    WHERE LOWER(a.alias) = LOWER(%s)
                    """,
                (alias,),
            )
            rows = await cur.fetchall()
            out: list[LibraryRecord] = []
            for row in rows:
                versions = await _list_versions(cur, row[0])
                out.append(_row_to_library(row, versions))
        return out

    async def fuzzy_search(self, query: str, *, limit: int) -> list[FuzzyMatch]:
        # Uses pg_trgm `similarity()`; descriptions weight half so name
        # matches dominate on typos.
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT id, name, description, homepage_url, doc_type,
                           latest_version, trust_score, chunk_count,
                           GREATEST(
                               similarity(name, %(q)s),
                               0.5 * COALESCE(similarity(description, %(q)s), 0)
                           ) AS sim
                    FROM libraries
                    WHERE name %% %(q)s OR description %% %(q)s
                    ORDER BY sim DESC
                    LIMIT %(lim)s
                    """,
                {"q": query, "lim": limit},
            )
            rows = await cur.fetchall()
            out: list[FuzzyMatch] = []
            for row in rows:
                versions = await _list_versions(cur, row[0])
                sim = float(row[8] or 0.0)
                out.append(
                    FuzzyMatch(
                        library=_row_to_library(row[:8], versions),
                        trgm_similarity=sim,
                    )
                )
        return out

    async def has_version(self, library_id: str, version: str) -> bool:
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM library_versions WHERE library_id = %s AND version = %s",
                (library_id, version),
            )
            return (await cur.fetchone()) is not None


async def _list_versions(cur: Any, library_id: str) -> list[str]:
    await cur.execute(
        "SELECT version FROM library_versions WHERE library_id = %s ORDER BY version DESC",
        (library_id,),
    )
    rows = await cur.fetchall()
    return [r[0] for r in rows]


def _row_to_library(row: Any, versions: list[str]) -> LibraryRecord:
    return LibraryRecord(
        id=row[0],
        name=row[1],
        description=row[2],
        homepage_url=row[3],
        doc_type=row[4],
        latest_version=row[5],
        trust_score=float(row[6] or 0.5),
        chunk_count=int(row[7] or 0),
        available_versions=versions,
    )


# --- PgRegistry factory -------------------------------------------------------


async def build_pg_registry(
    *,
    database_url: str,
    redis_client: Any | None = None,
    ttl_inproc: int = 600,
    ttl_redis: int = 300,
) -> tuple[Registry, Any]:
    """Construct a Postgres-backed :class:`Registry` and return it with the pool.

    Returns ``(registry, pool)`` so the caller can ``await pool.close()`` on
    shutdown.
    """
    from psycopg_pool import AsyncConnectionPool

    pg_url = _normalise_pg_url(database_url)
    pool = AsyncConnectionPool(pg_url, min_size=1, max_size=8, open=False)
    await pool.open()
    backend = PgBackend(pool)
    cache = TwoLayerCache(
        redis_client=redis_client,
        ttl_inproc=ttl_inproc,
        ttl_redis=ttl_redis,
    )
    return Registry(backend, cache=cache), pool


def _normalise_pg_url(url: str) -> str:
    """Strip the SQLAlchemy ``postgresql+psycopg://`` prefix used by the rest
    of the codebase. psycopg's connection string wants the bare scheme."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


__all__ = [
    "FuzzyMatch",
    "LibraryRecord",
    "MemoryBackend",
    "PgBackend",
    "Registry",
    "RegistryBackend",
    "TwoLayerCache",
    "build_pg_registry",
]
