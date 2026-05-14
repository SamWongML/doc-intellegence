"""Resource construction for the FastMCP server.

Splits the *what to build* from *how it gets attached to FastMCP* so tests can
build the same resources without spinning up the server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from doc_search_shared.clients.rag_search_client import (
    FakeRagSearchClient,
    RagSearchClient,
)
from doc_search_shared.logging import get_logger
from doc_search_shared.settings import Settings

from .registry import Registry, build_pg_registry

log = get_logger(__name__)


@dataclass
class Resources:
    """Bundle handed to every tool invocation."""

    registry: Registry
    search: RagSearchClient
    settings: Settings
    pool: Any | None = None
    redis: Any | None = None

    async def aclose(self) -> None:
        if self.pool is not None:
            try:
                await self.pool.close()
            except Exception as exc:  # pragma: no cover - shutdown best-effort
                log.warning("mcp.pool_close_failed", error=str(exc))
        if self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception as exc:  # pragma: no cover - shutdown best-effort
                log.warning("mcp.redis_close_failed", error=str(exc))


async def build_redis(settings: Settings) -> Any | None:
    """Best-effort Redis client. Falls back to ``None`` if Redis is offline."""
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover - dev fallback
        return None
    client: Any = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - misconfigured Redis
        log.warning("mcp.redis_unavailable", error=str(exc))
        return None
    return client


async def build_resources(settings: Settings | None = None) -> Resources:
    """Build production resources: Postgres-backed registry + Fake search client.

    The ``RagSearchClient`` stays a fake until Phase 6 wiring — see
    ``packages/shared/doc_search_shared/clients/rag_search_client.py``.
    """
    settings = settings or Settings()
    redis = await build_redis(settings)
    registry, pool = await build_pg_registry(
        database_url=settings.database_url,
        redis_client=redis,
    )
    search: RagSearchClient = FakeRagSearchClient()
    return Resources(
        registry=registry,
        search=search,
        settings=settings,
        pool=pool,
        redis=redis,
    )


__all__ = ["Resources", "build_redis", "build_resources"]
