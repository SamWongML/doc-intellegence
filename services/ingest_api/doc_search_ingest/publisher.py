"""SQS job enqueue + matching ``jobs`` row insert.

The ingest API is the *only* writer of ``jobs.state='queued'``. The worker
flips the row to ``running``/``succeeded``/``failed``. We persist the row
before sending to SQS so a poll of ``GET /jobs/{job_id}`` is consistent even
if the SQS send fails (we raise and the API caller sees a 500).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from doc_search_shared.db.tables import Job as JobRow
from doc_search_shared.ids import new_ulid
from doc_search_shared.models import Job, JobSource, Mode, Profile
from doc_search_shared.settings import Settings
from sqlalchemy.orm import Session


def queue_name_for_profile(profile: Profile, settings: Settings) -> str:
    return settings.sqs_queue_light if profile == "light" else settings.sqs_queue_heavy


class JobPublisher:
    """Insert ``jobs`` row + ``SendMessage`` to the matching FIFO queue."""

    def __init__(self, *, sqs: Any, settings: Settings) -> None:
        self._sqs = sqs
        self._settings = settings
        self._queue_url_cache: dict[str, str] = {}

    def _queue_url(self, queue_name: str) -> str:
        cached = self._queue_url_cache.get(queue_name)
        if cached:
            return cached
        url: str = self._sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        self._queue_url_cache[queue_name] = url
        return url

    def enqueue(
        self,
        *,
        session: Session,
        library_id: str,
        version: str | None,
        source: JobSource,
        mode: Mode,
        profile: Profile,
        trace_id: str | None = None,
        requested_by: str | None = None,
    ) -> Job:
        job = Job(
            job_id=new_ulid(),
            library_id=library_id,
            version=version,
            source=source,
            mode=mode,
            profile=profile,
            requested_by=requested_by,
            trace_id=trace_id,
            created_at=datetime.now(UTC),
        )

        session.add(
            JobRow(
                job_id=job.job_id,
                library_id=job.library_id,
                version=job.version,
                state="queued",
                source=job.source.model_dump(),
                mode=job.mode,
                profile=job.profile,
                trace_id=job.trace_id,
            )
        )
        session.flush()

        queue_name = queue_name_for_profile(profile, self._settings)
        self._sqs.send_message(
            QueueUrl=self._queue_url(queue_name),
            MessageBody=job.model_dump_json(),
            MessageGroupId=library_id,
        )
        return job


__all__ = ["JobPublisher", "queue_name_for_profile"]
