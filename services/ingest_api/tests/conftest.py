"""Shared fixtures for the ingest API test suite.

Strategy:
- In-memory SQLite with ``StaticPool`` so all sessions share one connection
  (mirrors a tiny Postgres for routing + smoke tests).
- moto's ``mock_aws`` for SQS + EventBridge Scheduler. The fixture creates the
  FIFO queue + scheduler group up front.
- A test ``lifespan`` wires state directly so the production lifespan (which
  needs a real Postgres + Redis) never runs under TestClient.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import boto3
import pytest
from doc_search_ingest.app import create_app
from doc_search_ingest.publisher import JobPublisher
from doc_search_ingest.rate_limit import InMemoryRateLimiter
from doc_search_ingest.scheduler import SchedulerClient
from doc_search_shared.db.tables import Base
from doc_search_shared.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aws_endpoint_url=None,
        aws_region="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        sqs_queue_light="doc-search-light.fifo",
        sqs_queue_heavy="doc-search-heavy.fifo",
        scheduler_role_arn="arn:aws:iam::123456789012:role/scheduler",
        scheduler_target_arn=("arn:aws:sqs:us-east-1:123456789012:doc-search-light.fifo"),
        scheduler_group_name="default",
        ingest_api_keys="",  # auth disabled in tests
        ingest_rate_limit_per_min=60,
        github_webhook_secret="testsecret",
    )


@pytest.fixture
def db_sessionmaker() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield sm
    engine.dispose()


@pytest.fixture
def aws() -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def sqs_client(aws: None, settings: Settings) -> Any:
    client = boto3.client("sqs", region_name=settings.aws_region)
    for name in (settings.sqs_queue_light, settings.sqs_queue_heavy):
        client.create_queue(
            QueueName=name,
            Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
        )
    return client


@pytest.fixture
def scheduler_client(aws: None, settings: Settings) -> Any:
    client = boto3.client("scheduler", region_name=settings.aws_region)
    return client


@pytest.fixture
def app(
    settings: Settings,
    db_sessionmaker: sessionmaker[Session],
    sqs_client: Any,
    scheduler_client: Any,
) -> FastAPI:
    publisher = JobPublisher(sqs=sqs_client, settings=settings)
    sched = SchedulerClient(scheduler=scheduler_client, settings=settings)
    limiter = InMemoryRateLimiter()

    @asynccontextmanager
    async def _test_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _app.state.sessionmaker = db_sessionmaker
        _app.state.sqs = sqs_client
        _app.state.scheduler_client = scheduler_client
        _app.state.publisher = publisher
        _app.state.scheduler = sched
        _app.state.rate_limiter = limiter
        yield

    app = create_app(settings=settings, lifespan_fn=_test_lifespan)
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
