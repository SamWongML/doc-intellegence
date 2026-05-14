"""SQLAlchemy 2.0 table definitions matching `contracts.md` §E."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Use JSONB on Postgres, fall back to JSON elsewhere (SQLite in tests).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Library(Base):
    __tablename__ = "libraries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    org: Mapped[str] = mapped_column(String, nullable=False)
    project: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    homepage_url: Mapped[str | None] = mapped_column(String, nullable=True)
    doc_source: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    doc_type: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LibraryAlias(Base):
    __tablename__ = "library_aliases"

    alias: Mapped[str] = mapped_column(String, primary_key=True)
    library_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("libraries.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (Index("ix_aliases_alias_lower", text("lower(alias)")),)


class LibraryVersion(Base):
    __tablename__ = "library_versions"

    library_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("libraries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[str] = mapped_column(String, primary_key=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    library_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    docs_total: Mapped[int] = mapped_column(Integer, default=0)
    docs_processed: Mapped[int] = mapped_column(Integer, default=0)
    docs_reused: Mapped[int] = mapped_column(Integer, default=0)
    docs_failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Migration adds the DESC ordering on created_at; the ORM index is
        # plain since `MappedColumn.desc()` is awkward in __table_args__.
        Index("ix_jobs_library", "library_id", "created_at"),
    )


class ChunkInventory(Base):
    __tablename__ = "chunk_inventory"

    library_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Composite-PK columns must be NOT NULL in Postgres. We use a sentinel
    # `_unversioned` for libraries without a version (mirrors S3 layout).
    version: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_job: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_inventory_hash", "library_id", "content_hash"),)


__all__ = [
    "Base",
    "ChunkInventory",
    "Job",
    "Library",
    "LibraryAlias",
    "LibraryVersion",
]
