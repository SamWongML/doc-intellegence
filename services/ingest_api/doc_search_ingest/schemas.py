"""Request/response models for the ingest API.

These are HTTP-layer DTOs; they sit on top of the shared ``Job`` / DB tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from doc_search_shared.models import JobSource, JobState, Mode, Profile
from pydantic import BaseModel, ConfigDict, Field


class RegisterLibraryRequest(BaseModel):
    """Body for ``POST /libraries``."""

    model_config = ConfigDict(extra="forbid")

    library_id: str = Field(description="Canonical /org/project[/version] id.")
    name: str
    description: str | None = None
    homepage_url: str | None = None
    doc_source: JobSource
    doc_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    trust_score: float = 0.5
    refresh_schedule: str | None = Field(
        default=None,
        description="EventBridge ScheduleExpression. e.g. cron(0 6 * * ? *)",
    )
    profile: Profile = "light"


class LibrarySummary(BaseModel):
    """Row in ``GET /libraries``."""

    model_config = ConfigDict(extra="forbid")

    library_id: str
    name: str
    description: str | None
    homepage_url: str | None
    doc_type: str | None
    latest_version: str | None
    last_indexed_at: datetime | None
    chunk_count: int
    trust_score: float


class JobSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    library_id: str
    version: str | None
    state: JobState
    mode: Mode
    profile: Profile
    docs_total: int
    docs_processed: int
    docs_failed: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class LibraryDetail(LibrarySummary):
    """Body of ``GET /libraries/{id}``."""

    aliases: list[str]
    versions: list[str]
    recent_jobs: list[JobSummary]


class EnqueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    library_id: str
    state: Literal["queued"] = "queued"


class WebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    enqueued_jobs: list[str] = Field(default_factory=list)
    reason: str | None = None


__all__ = [
    "EnqueueResponse",
    "JobSummary",
    "LibraryDetail",
    "LibrarySummary",
    "RegisterLibraryRequest",
    "WebhookResponse",
]
