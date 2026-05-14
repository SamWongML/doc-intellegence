"""Pydantic v2 contracts shared by worker, ingest API, and MCP server.

See `docs/implementation/contracts.md` sections A-C. Any change here is a
breaking change across services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobState = Literal["queued", "running", "succeeded", "failed", "skipped"]
SourceType = Literal["github", "http_url", "openapi", "llms_full", "local_path"]
Profile = Literal["light", "heavy"]
Mode = Literal["full", "incremental"]
DocType = Literal["guide", "reference", "openapi_endpoint", "tutorial", "other"]


# --- A. Job (SQS message body) -------------------------------------------------


class JobSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    url: str
    ref: str | None = None
    doc_paths: list[str] = Field(default_factory=list)
    openapi_url: str | None = None


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    library_id: str
    version: str | None = None
    source: JobSource
    mode: Mode = "full"
    profile: Profile
    requested_by: str | None = None
    trace_id: str | None = None
    created_at: datetime


# --- B. ProcessedDocument (worker → RAG handoff) -------------------------------


class CodeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str | None = None
    content: str


class ProcessedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    library_id: str
    version: str | None = None
    source_url: str
    title: str
    breadcrumbs: list[str] = Field(default_factory=list)
    doc_type: DocType
    language_tags: list[str] = Field(default_factory=list)
    markdown: str
    anchors: dict[str, str] = Field(default_factory=dict)
    openapi_spec: dict[str, Any] | None = None
    openapi_summary: str | None = None
    content_hash: str
    extracted_at: datetime


# --- C. JobStatus (RDS row updated by worker) ---------------------------------


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    library_id: str
    state: JobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    docs_total: int = 0
    docs_processed: int = 0
    docs_reused: int = 0
    docs_failed: int = 0
    error: str | None = None
    trace_id: str | None = None


__all__ = [
    "CodeBlock",
    "DocType",
    "Job",
    "JobSource",
    "JobState",
    "JobStatus",
    "Mode",
    "ProcessedDocument",
    "Profile",
    "SourceType",
]
