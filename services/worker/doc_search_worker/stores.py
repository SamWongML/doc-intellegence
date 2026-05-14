"""Side-effect ports the runner depends on: job-state DB row, artifact upload.

Both have a no-op default so the worker can run in tests / dev without
Postgres + S3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from doc_search_shared.db.tables import Job as JobRow
from doc_search_shared.models import Job
from doc_search_shared.s3 import artifact_path
from sqlalchemy.orm import Session, sessionmaker

from .logging_utils import log
from .pipeline import JobOutcome


class JobStateStore(Protocol):
    def mark_running(self, job: Job) -> None: ...
    def mark_succeeded(self, job: Job, outcome: JobOutcome) -> None: ...
    def mark_failed(self, job: Job, error: str) -> None: ...


class ArtifactStore(Protocol):
    def upload_jsonl(self, job: Job, payload: bytes) -> str | None: ...


class NullJobStateStore:
    """Used in tests + when no Postgres is configured."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def mark_running(self, job: Job) -> None:
        self.events.append((job.job_id, "running"))

    def mark_succeeded(self, job: Job, outcome: JobOutcome) -> None:
        self.events.append((job.job_id, "succeeded"))

    def mark_failed(self, job: Job, error: str) -> None:
        self.events.append((job.job_id, "failed"))


class NullArtifactStore:
    """Discards artifact bytes; records the key for inspection."""

    def __init__(self) -> None:
        self.uploaded: list[tuple[str, int]] = []

    def upload_jsonl(self, job: Job, payload: bytes) -> str | None:
        key = artifact_path(job.library_id, job.version, job.job_id, "documents.jsonl")
        self.uploaded.append((key, len(payload)))
        return key


class SqlJobStateStore:
    """Postgres-backed job state via SQLAlchemy."""

    def __init__(self, sm: sessionmaker[Session]) -> None:
        self._sm = sm

    def mark_running(self, job: Job) -> None:
        with self._sm() as session:
            row = session.get(JobRow, job.job_id)
            now = datetime.now(UTC)
            if row is None:
                session.add(_make_row(job, state="running", started_at=now))
            else:
                row.state = "running"
                row.started_at = now
            session.commit()

    def mark_succeeded(self, job: Job, outcome: JobOutcome) -> None:
        with self._sm() as session:
            row = session.get(JobRow, job.job_id)
            now = datetime.now(UTC)
            if row is None:
                row = _make_row(job, state="succeeded", started_at=now)
                session.add(row)
            row.state = "succeeded"
            row.finished_at = now
            row.docs_total = outcome.docs_total
            row.docs_processed = outcome.docs_processed
            row.docs_failed = outcome.docs_failed
            session.commit()

    def mark_failed(self, job: Job, error: str) -> None:
        with self._sm() as session:
            row = session.get(JobRow, job.job_id)
            now = datetime.now(UTC)
            if row is None:
                row = _make_row(job, state="failed", started_at=now)
                session.add(row)
            row.state = "failed"
            row.finished_at = now
            row.error = (error or "")[:1000]
            session.commit()


class S3ArtifactStore:
    """Uploads JSONL artifacts to S3 under ``artifacts/<lib>/<ver>/<job>/...``."""

    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def upload_jsonl(self, job: Job, payload: bytes) -> str | None:
        key = artifact_path(job.library_id, job.version, job.job_id, "documents.jsonl")
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=payload,
            ContentType="application/x-ndjson",
        )
        log.info("artifact.uploaded", bucket=self._bucket, key=key, bytes=len(payload))
        return key


def _make_row(job: Job, *, state: str, started_at: datetime) -> JobRow:
    return JobRow(
        job_id=job.job_id,
        library_id=job.library_id,
        version=job.version,
        state=state,
        source=job.source.model_dump(),
        mode=job.mode,
        profile=job.profile,
        started_at=started_at,
        trace_id=job.trace_id,
    )


__all__ = [
    "ArtifactStore",
    "JobStateStore",
    "NullArtifactStore",
    "NullJobStateStore",
    "S3ArtifactStore",
    "SqlJobStateStore",
]
