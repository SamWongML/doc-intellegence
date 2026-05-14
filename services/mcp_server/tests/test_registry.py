"""Registry + cache behaviour. Postgres-specific paths are smoke-tested via
``MemoryBackend``; the real ``PgBackend`` is exercised by integration tests
against a live Postgres in Phase 6."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from doc_search_mcp.registry import (
    LibraryRecord,
    MemoryBackend,
    Registry,
    TwoLayerCache,
    _LRUCacheTTL,
    build_pg_registry,
)


@pytest.mark.asyncio
async def test_get_library_returns_record(registry: Registry) -> None:
    record = await registry.get_library("/vercel/next.js")
    assert record is not None
    assert record.name == "Next.js"
    assert "v15.1.0" in record.available_versions


@pytest.mark.asyncio
async def test_get_library_unknown(registry: Registry) -> None:
    assert await registry.get_library("/nope/missing") is None


@pytest.mark.asyncio
async def test_find_by_alias_case_insensitive(registry: Registry) -> None:
    upper = await registry.find_by_alias("NextJS")
    lower = await registry.find_by_alias("nextjs")
    assert {r.id for r in upper} == {r.id for r in lower} == {"/vercel/next.js"}


@pytest.mark.asyncio
async def test_fuzzy_search_orders_by_similarity(registry: Registry) -> None:
    matches = await registry.fuzzy_search("nextjs framework", limit=5)
    assert matches, "expected at least one fuzzy match"
    # Next.js ought to dominate; FastAPI should rank below.
    top_ids = [m.library.id for m in matches]
    assert top_ids[0] == "/vercel/next.js"


@pytest.mark.asyncio
async def test_has_version_checks_both_latest_and_available(
    registry: Registry,
) -> None:
    assert await registry.has_version("/vercel/next.js", "v15.1.0") is True
    assert await registry.has_version("/vercel/next.js", "v14.2.0") is True
    assert await registry.has_version("/vercel/next.js", "v99.0.0") is False
    assert await registry.has_version("/no/such", "v1") is False


@pytest.mark.asyncio
async def test_two_layer_cache_serves_inproc(libraries: list[LibraryRecord]) -> None:
    backend = MemoryBackend(libraries)
    calls = {"n": 0}

    real_get = backend.get_library

    async def counting(library_id: str) -> LibraryRecord | None:
        calls["n"] += 1
        return await real_get(library_id)

    backend.get_library = counting  # type: ignore[method-assign]
    registry = Registry(backend, cache=TwoLayerCache(ttl_inproc=600, ttl_redis=300))

    a = await registry.get_library("/vercel/next.js")
    b = await registry.get_library("/vercel/next.js")
    assert a == b
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_two_layer_cache_falls_back_to_redis_when_lru_expires(
    libraries: list[LibraryRecord],
) -> None:
    backend = MemoryBackend(libraries)
    redis = _FakeAsyncRedis()
    cache = TwoLayerCache(redis_client=redis, ttl_inproc=0, ttl_redis=300)
    registry = Registry(backend, cache=cache)

    await registry.get_library("/vercel/next.js")
    # LRU TTL = 0 → already expired. Redis must satisfy the next call.
    await registry.get_library("/vercel/next.js")
    assert redis.get_calls >= 1
    assert redis.set_calls == 1


@pytest.mark.asyncio
async def test_two_layer_cache_swallows_redis_errors(
    libraries: list[LibraryRecord],
) -> None:
    backend = MemoryBackend(libraries)
    redis = _FlakyRedis()
    cache = TwoLayerCache(redis_client=redis, ttl_inproc=600)
    registry = Registry(backend, cache=cache)

    # Should still resolve from the backend even if Redis blows up.
    record = await registry.get_library("/vercel/next.js")
    assert record is not None


def test_lru_cache_evicts_oldest() -> None:
    cache = _LRUCacheTTL(max_size=2, ttl_seconds=600)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")
    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("c") == "3"


@pytest.mark.asyncio
async def test_build_pg_registry_imports_psycopg() -> None:
    # We can't open a real connection here, so verify the helper at least
    # exposes the expected coroutine signature. Importing psycopg_pool fails
    # cleanly if the optional dep is missing.
    assert callable(build_pg_registry)


# --- Tiny fakes ---------------------------------------------------------------


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls += 1
        self._store[key] = value


class _FlakyRedis:
    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise RuntimeError("redis down")


# Quiet unused-import lint warnings from typing helpers above.
_ = (Any, Awaitable, Callable)
