"""SQS poll loop, heartbeat, ack/NACK, graceful SIGTERM.

The runner is the only place that touches SQS, S3, and Postgres directly —
``pipeline.process_job`` is pure (no IO besides the RAG client + source
fetchers it composes).
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from typing import Any

import boto3
from doc_search_shared.clients import FakeRagEmbeddingClient, RagEmbeddingClient
from doc_search_shared.logging import bind, clear
from doc_search_shared.models import Job
from doc_search_shared.settings import Settings

from .logging_utils import log
from .pipeline import JobOutcome, process_job
from .stores import (
    ArtifactStore,
    JobStateStore,
    NullJobStateStore,
    S3ArtifactStore,
)

WAIT_SECONDS = 20
VISIBILITY_TIMEOUT = 300
HEARTBEAT_INTERVAL = 60


def _aws_client(service: str, settings: Settings) -> Any:
    return boto3.client(
        service,
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


class Runner:
    def __init__(
        self,
        *,
        settings: Settings,
        client: RagEmbeddingClient,
        sqs: Any,
        queue_url: str,
        job_store: JobStateStore,
        artifact_store: ArtifactStore,
    ) -> None:
        self.settings = settings
        self.client = client
        self.sqs = sqs
        self.queue_url = queue_url
        self.job_store = job_store
        self.artifact_store = artifact_store
        self._stop = asyncio.Event()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Runner:
        settings = settings or Settings()
        sqs = _aws_client("sqs", settings)
        queue_name = _queue_name(settings)
        queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        s3 = _aws_client("s3", settings)
        return cls(
            settings=settings,
            client=FakeRagEmbeddingClient(),
            sqs=sqs,
            queue_url=queue_url,
            job_store=NullJobStateStore(),
            artifact_store=S3ArtifactStore(s3, settings.s3_bucket_artifacts),
        )

    def request_stop(self) -> None:
        if not self._stop.is_set():
            log.info("runner.sigterm_received")
            self._stop.set()

    async def run_forever(self) -> None:
        log.info(
            "runner.start",
            queue=self.queue_url,
            profile=self.settings.worker_profile,
        )
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except Exception as exc:  # pragma: no cover - top-level loop guard
                log.exception("runner.poll_error", error=str(exc))
                await asyncio.sleep(1)
        log.info("runner.stop")

    async def poll_once(self) -> int:
        """Long-poll once. Returns the number of messages handled."""
        resp = await asyncio.to_thread(
            self.sqs.receive_message,
            QueueUrl=self.queue_url,
            WaitTimeSeconds=WAIT_SECONDS,
            MaxNumberOfMessages=1,
            VisibilityTimeout=VISIBILITY_TIMEOUT,
        )
        messages = resp.get("Messages") or []
        for msg in messages:
            await self._handle_message(msg)
        return len(messages)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        body = msg.get("Body", "") or ""
        receipt = msg["ReceiptHandle"]
        try:
            job = Job.model_validate_json(body)
        except Exception as exc:
            log.error(
                "runner.bad_message",
                error=str(exc),
                body_preview=body[:200],
            )
            # Delete malformed messages so the DLQ doesn't fill with garbage;
            # ingest API is responsible for shape.
            await asyncio.to_thread(
                self.sqs.delete_message,
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt,
            )
            return

        bind(job_id=job.job_id, trace_id=job.trace_id or "")
        heartbeat = asyncio.create_task(self._heartbeat(receipt))
        try:
            await self._run_job(job)
            await asyncio.to_thread(
                self.sqs.delete_message,
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt,
            )
        except Exception as exc:
            log.exception("runner.job_failed", error=str(exc))
            self.job_store.mark_failed(job, str(exc))
            with suppress(Exception):
                # NACK by zeroing visibility so SQS redrives ASAP (DLQ at >5).
                await asyncio.to_thread(
                    self.sqs.change_message_visibility,
                    QueueUrl=self.queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=0,
                )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            clear()

    async def _run_job(self, job: Job) -> JobOutcome:
        self.job_store.mark_running(job)
        outcome = await process_job(job, client=self.client)
        self.artifact_store.upload_jsonl(job, outcome.artifact_jsonl)
        self.job_store.mark_succeeded(job, outcome)
        log.info(
            "runner.job_succeeded",
            docs_total=outcome.docs_total,
            docs_processed=outcome.docs_processed,
            docs_failed=outcome.docs_failed,
            chunk_count=outcome.chunk_count,
        )
        return outcome

    async def _heartbeat(self, receipt: str) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await asyncio.to_thread(
                    self.sqs.change_message_visibility,
                    QueueUrl=self.queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=VISIBILITY_TIMEOUT,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - log + continue
            log.warning("runner.heartbeat_error", error=str(exc))


def _queue_name(settings: Settings) -> str:
    return (
        settings.sqs_queue_light if settings.worker_profile == "light" else settings.sqs_queue_heavy
    )


def install_signal_handlers(runner: Runner, loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, runner.request_stop)
        except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: runner.request_stop())


__all__ = [
    "HEARTBEAT_INTERVAL",
    "VISIBILITY_TIMEOUT",
    "WAIT_SECONDS",
    "Runner",
    "install_signal_handlers",
]
