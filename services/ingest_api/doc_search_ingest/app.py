"""FastAPI app factory.

The app is constructed by :func:`create_app`; ``__main__`` either binds it to
uvicorn (Fargate/dev) or wraps it with Mangum for AWS Lambda. The same module
is imported in both runtimes, so wiring (DB, SQS, Redis, Scheduler) lives in
a single ``lifespan`` callback.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import boto3
from doc_search_shared.db.engine import get_sessionmaker
from doc_search_shared.logging import configure_logging, get_logger
from doc_search_shared.settings import Settings
from fastapi import FastAPI

from .publisher import JobPublisher
from .rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from .routes import github as github_routes
from .routes import jobs as jobs_routes
from .routes import libraries as libraries_routes
from .scheduler import SchedulerClient

LifespanFn = Callable[[FastAPI], AbstractAsyncContextManager[None]]

log = get_logger(__name__)


def _aws_client(service: str, settings: Settings) -> Any:
    kwargs: dict[str, Any] = dict(
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client(service, **kwargs)


async def _build_rate_limiter(settings: Settings) -> RateLimiter:
    if not settings.redis_url:
        return InMemoryRateLimiter()
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover - dev fallback
        return InMemoryRateLimiter()
    client: Any = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - misconfigured Redis
        log.warning("rate_limit.redis_unavailable", error=str(exc))
        return InMemoryRateLimiter()
    return RedisRateLimiter(client)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, json=settings.log_json)

    app.state.sessionmaker = get_sessionmaker()
    app.state.sqs = _aws_client("sqs", settings)
    app.state.scheduler_client = _aws_client("scheduler", settings)
    app.state.publisher = JobPublisher(sqs=app.state.sqs, settings=settings)
    app.state.scheduler = SchedulerClient(scheduler=app.state.scheduler_client, settings=settings)
    app.state.rate_limiter = await _build_rate_limiter(settings)
    log.info("ingest_api.start", scheduler_enabled=app.state.scheduler.is_enabled())
    try:
        yield
    finally:
        log.info("ingest_api.stop")


def create_app(
    settings: Settings | None = None,
    *,
    lifespan_fn: LifespanFn | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Doc-Search Ingest API",
        version="0.1.0",
        description="Register libraries, refresh, query jobs, accept GitHub webhooks.",
        lifespan=lifespan_fn or lifespan,
    )
    app.state.settings = settings
    app.include_router(libraries_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(github_routes.router)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


__all__ = ["create_app", "lifespan"]
