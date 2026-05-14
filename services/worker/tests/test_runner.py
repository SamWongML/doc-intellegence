"""Runner: SQS poll + ack + artifact upload via moto."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pytest
from doc_search_shared.clients import FakeRagEmbeddingClient
from doc_search_shared.models import Job, JobSource
from doc_search_shared.settings import Settings
from doc_search_worker.runner import Runner
from doc_search_worker.sources import github as github_source
from doc_search_worker.stores import (
    NullArtifactStore,
    NullJobStateStore,
    S3ArtifactStore,
)
from moto import mock_aws


@contextmanager
def _yield_path(path: Path) -> Iterator[Path]:
    yield path


def _make_job(source: JobSource) -> Job:
    return Job(
        job_id="01HQ8TSN8YJV4Q4Z3M9T9S0Q3W",
        library_id="/vercel/next.js",
        version="v15.1.0",
        source=source,
        mode="full",
        profile="light",
        created_at=datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aws_endpoint_url=None,
        aws_region="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        s3_bucket_artifacts="doc-search-artifacts",
    )


@pytest.mark.asyncio
async def test_runner_processes_one_message(
    monkeypatch: pytest.MonkeyPatch,
    sample_repo_dir: Path,
    settings: Settings,
) -> None:
    # Pretend pygit2 cloned: yield the fixture dir.
    monkeypatch.setattr(
        github_source, "pygit2_clone", lambda url, ref: _yield_path(sample_repo_dir)
    )

    with mock_aws():
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        s3 = boto3.client("s3", region_name=settings.aws_region)
        queue_url = sqs.create_queue(QueueName="doc-search-light")["QueueUrl"]
        s3.create_bucket(Bucket=settings.s3_bucket_artifacts)

        job = _make_job(
            JobSource(
                type="github",
                url="https://github.com/vercel/next.js",
                doc_paths=["docs/**/*.md", "docs/**/*.mdx"],
            )
        )
        sqs.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())

        job_store = NullJobStateStore()
        artifact_store = S3ArtifactStore(s3, settings.s3_bucket_artifacts)
        runner = Runner(
            settings=settings,
            client=FakeRagEmbeddingClient(),
            sqs=sqs,
            queue_url=queue_url,
            job_store=job_store,
            artifact_store=artifact_store,
        )

        handled = await _poll_no_wait(runner)
        assert handled == 1

        # Queue is now empty (message was deleted on success).
        remaining = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0
        )
        assert "Messages" not in remaining or not remaining["Messages"]

        # Artifact lands in S3.
        keys = [
            o["Key"]
            for o in s3.list_objects_v2(Bucket=settings.s3_bucket_artifacts).get("Contents", [])
        ]
        assert any(k.endswith(f"/{job.job_id}/documents.jsonl") for k in keys)

        assert (job.job_id, "running") in job_store.events
        assert (job.job_id, "succeeded") in job_store.events


@pytest.mark.asyncio
async def test_runner_nacks_on_failure(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    def boom(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("clone exploded")

    monkeypatch.setattr(github_source, "pygit2_clone", boom)

    with mock_aws():
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        queue_url = sqs.create_queue(QueueName="doc-search-light")["QueueUrl"]
        job = _make_job(
            JobSource(
                type="github",
                url="https://github.com/foo/bar",
                doc_paths=["docs/**/*.md"],
            )
        )
        sqs.send_message(QueueUrl=queue_url, MessageBody=job.model_dump_json())

        job_store = NullJobStateStore()
        runner = Runner(
            settings=settings,
            client=FakeRagEmbeddingClient(),
            sqs=sqs,
            queue_url=queue_url,
            job_store=job_store,
            artifact_store=NullArtifactStore(),
        )
        handled = await _poll_no_wait(runner)
        assert handled == 1
        # Failure marked on store.
        assert (job.job_id, "failed") in job_store.events

        # Message is back on the queue (visibility was reset to 0).
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0)
        assert resp.get("Messages")


@pytest.mark.asyncio
async def test_runner_deletes_malformed_message(settings: Settings) -> None:
    with mock_aws():
        sqs = boto3.client("sqs", region_name=settings.aws_region)
        queue_url = sqs.create_queue(QueueName="doc-search-light")["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody="{not valid json")

        runner = Runner(
            settings=settings,
            client=FakeRagEmbeddingClient(),
            sqs=sqs,
            queue_url=queue_url,
            job_store=NullJobStateStore(),
            artifact_store=NullArtifactStore(),
        )
        handled = await _poll_no_wait(runner)
        assert handled == 1
        # Garbage message is deleted (won't redrive infinitely).
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0)
        assert "Messages" not in resp or not resp["Messages"]


async def _poll_no_wait(runner: Runner) -> int:
    """Call ``poll_once`` with a 0-second wait so tests don't block 20 seconds."""
    original_receive = runner.sqs.receive_message

    def quick(**kwargs: Any) -> Any:
        kwargs["WaitTimeSeconds"] = 0
        return original_receive(**kwargs)

    runner.sqs.receive_message = quick
    return await runner.poll_once()
