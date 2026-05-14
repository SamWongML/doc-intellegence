"""Sliding-window rate limiter.

Two implementations: Redis-backed for prod, in-memory for tests + single-replica
dev. Both implement :class:`RateLimiter`. The 429 is raised via
``HTTPException`` so FastAPI handles the response.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol

from fastapi import HTTPException, status

WINDOW_SECONDS = 60


class RateLimiter(Protocol):
    async def check(self, key: str, limit: int) -> None: ...


class InMemoryRateLimiter:
    """Process-local sliding window. Fine for tests and single-replica dev."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def check(self, key: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        bucket = self._hits[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )
        bucket.append(now)


class RedisRateLimiter:
    """Redis-backed sliding window.

    Uses a sorted set per key: scores are unix timestamps, members are unique
    request markers. ZREMRANGEBYSCORE trims expired hits before counting.
    """

    def __init__(self, redis_client: object) -> None:
        # Loose typing: this accepts either ``redis.asyncio.Redis`` or
        # ``fakeredis.aioredis.FakeRedis`` (both expose the same protocol).
        self._redis = redis_client

    async def check(self, key: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.time()
        cutoff = now - WINDOW_SECONDS
        redis_key = f"ratelimit:{key}"
        member = f"{now:.6f}:{id(self)}"

        pipe = self._redis.pipeline()  # type: ignore[attr-defined]
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zcard(redis_key)
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 1)
        _, count, _, _ = await pipe.execute()

        if count >= limit:
            # We already added, so subtract our own entry on overflow to keep
            # the window honest.
            await self._redis.zrem(redis_key, member)  # type: ignore[attr-defined]
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
            )


__all__ = ["WINDOW_SECONDS", "InMemoryRateLimiter", "RateLimiter", "RedisRateLimiter"]
