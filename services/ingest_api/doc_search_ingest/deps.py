"""FastAPI dependency providers.

Resources live on ``app.state`` and are constructed once in the lifespan; the
``Depends(...)`` callables below just hand them out. Tests override these via
``app.dependency_overrides`` rather than monkeypatching globals.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from doc_search_shared.settings import Settings
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .auth import authenticate
from .publisher import JobPublisher
from .rate_limit import RateLimiter
from .scheduler import SchedulerClient


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_session(request: Request) -> Iterator[Session]:
    sm = request.app.state.sessionmaker
    with sm() as session:
        yield session


def get_publisher(request: Request) -> JobPublisher:
    return request.app.state.publisher  # type: ignore[no-any-return]


def get_scheduler(request: Request) -> SchedulerClient:
    return request.app.state.scheduler  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def get_sqs(request: Request) -> Any:
    return request.app.state.sqs


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
PublisherDep = Annotated[JobPublisher, Depends(get_publisher)]
SchedulerDep = Annotated[SchedulerClient, Depends(get_scheduler)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


async def authenticate_request(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    return authenticate(x_api_key, settings)


async def authenticated_and_limited(
    settings: SettingsDep,
    limiter: RateLimiterDep,
    principal: Annotated[str, Depends(authenticate_request)],
) -> str:
    await limiter.check(principal, settings.ingest_rate_limit_per_min)
    return principal


PrincipalDep = Annotated[str, Depends(authenticated_and_limited)]


__all__ = [
    "PrincipalDep",
    "PublisherDep",
    "RateLimiterDep",
    "SchedulerDep",
    "SessionDep",
    "SettingsDep",
    "authenticate_request",
    "authenticated_and_limited",
    "get_publisher",
    "get_rate_limiter",
    "get_scheduler",
    "get_session",
    "get_settings",
    "get_sqs",
]
