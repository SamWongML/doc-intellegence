"""SQS publisher: row insert + FIFO send."""

from __future__ import annotations

import json
from typing import Any

from doc_search_ingest.publisher import JobPublisher, queue_name_for_profile
from doc_search_shared.db.tables import Job as JobRow
from doc_search_shared.models import JobSource
from doc_search_shared.settings import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def test_queue_routing() -> None:
    s = Settings()
    assert queue_name_for_profile("light", s) == s.sqs_queue_light
    assert queue_name_for_profile("heavy", s) == s.sqs_queue_heavy


def test_enqueue_inserts_row_and_sends(
    sqs_client: Any,
    settings: Settings,
    db_sessionmaker: sessionmaker[Session],
) -> None:
    pub = JobPublisher(sqs=sqs_client, settings=settings)
    source = JobSource(
        type="github",
        url="https://github.com/vercel/next.js",
        doc_paths=["docs/**/*.md"],
    )
    with db_sessionmaker() as session:
        job = pub.enqueue(
            session=session,
            library_id="/vercel/next.js",
            version=None,
            source=source,
            mode="full",
            profile="light",
            requested_by="tester",
        )
        session.commit()

    with db_sessionmaker() as session:
        row = session.execute(select(JobRow).where(JobRow.job_id == job.job_id)).scalar_one()
        assert row.state == "queued"
        assert row.library_id == "/vercel/next.js"

    queue_url = sqs_client.get_queue_url(QueueName=settings.sqs_queue_light)["QueueUrl"]
    msgs = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0)
    assert "Messages" in msgs
    body = json.loads(msgs["Messages"][0]["Body"])
    assert body["job_id"] == job.job_id
    assert body["mode"] == "full"


def test_enqueue_heavy_routes_to_heavy_queue(
    sqs_client: Any,
    settings: Settings,
    db_sessionmaker: sessionmaker[Session],
) -> None:
    pub = JobPublisher(sqs=sqs_client, settings=settings)
    source = JobSource(
        type="github",
        url="https://github.com/foo/bar",
        doc_paths=["docs/**/*.md"],
    )
    with db_sessionmaker() as session:
        pub.enqueue(
            session=session,
            library_id="/foo/bar",
            version=None,
            source=source,
            mode="full",
            profile="heavy",
        )
        session.commit()

    queue_url = sqs_client.get_queue_url(QueueName=settings.sqs_queue_heavy)["QueueUrl"]
    msgs = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0)
    assert "Messages" in msgs
