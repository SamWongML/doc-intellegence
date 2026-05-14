"""Process settings sourced from env (and `.env` if present)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOC_SEARCH_",
        extra="ignore",
    )

    # Postgres
    database_url: str = Field(
        default="postgresql+psycopg://docsearch:docsearch@localhost:5432/docsearch",
        description="SQLAlchemy URL for Postgres.",
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # AWS (LocalStack defaults)
    aws_endpoint_url: str | None = Field(default="http://localhost:4566")
    aws_region: str = Field(default="us-east-1")
    aws_access_key_id: str = Field(default="test")
    aws_secret_access_key: str = Field(default="test")

    # S3 buckets
    s3_bucket_raw: str = Field(default="doc-search-raw")
    s3_bucket_markdown: str = Field(default="doc-search-markdown")
    s3_bucket_artifacts: str = Field(default="doc-search-artifacts")

    # SQS queues
    sqs_queue_light: str = Field(default="doc-search-light.fifo")
    sqs_queue_heavy: str = Field(default="doc-search-heavy.fifo")

    # Worker profile
    worker_profile: str = Field(default="light")

    # Observability
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)


__all__ = ["Settings"]
