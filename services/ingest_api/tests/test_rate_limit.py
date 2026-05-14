"""Sliding-window limiter: in-memory + Redis (fakeredis)."""

from __future__ import annotations

import pytest
from doc_search_ingest.rate_limit import (
    InMemoryRateLimiter,
    RedisRateLimiter,
)
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_in_memory_allows_under_limit() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        await limiter.check("key", limit=5)


@pytest.mark.asyncio
async def test_in_memory_rejects_over_limit() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.check("key", limit=3)
    with pytest.raises(HTTPException) as exc:
        await limiter.check("key", limit=3)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_in_memory_zero_limit_disables() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(1000):
        await limiter.check("key", limit=0)


@pytest.mark.asyncio
async def test_redis_rate_limit_with_fakeredis() -> None:
    fakeredis = pytest.importorskip("fakeredis")
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(redis)
    for _ in range(3):
        await limiter.check("user:1", limit=3)
    with pytest.raises(HTTPException) as exc:
        await limiter.check("user:1", limit=3)
    assert exc.value.status_code == 429
    # Different key gets its own bucket.
    await limiter.check("user:2", limit=3)
