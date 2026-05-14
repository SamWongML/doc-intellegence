"""Seed local dev stack: 3 libraries + S3 buckets + SQS FIFO queues.

Idempotent — safe to re-run.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from doc_search_shared.db.engine import get_engine
from doc_search_shared.db.tables import Library, LibraryAlias, LibraryVersion
from doc_search_shared.logging import configure_logging, get_logger
from doc_search_shared.settings import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session

SEED_LIBRARIES = [
    {
        "id": "/vercel/next.js",
        "org": "vercel",
        "project": "next.js",
        "name": "Next.js",
        "description": "The React framework for the web.",
        "homepage_url": "https://nextjs.org",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/vercel/next.js",
            "doc_paths": ["docs/**/*.mdx"],
        },
        "doc_type": "guide",
        "latest_version": "v15.1.0",
        "aliases": ["next", "nextjs", "next.js"],
        "versions": ["v15.1.0", "v14.2.0"],
    },
    {
        "id": "/tiangolo/fastapi",
        "org": "tiangolo",
        "project": "fastapi",
        "name": "FastAPI",
        "description": "Modern, high-performance web framework for Python APIs.",
        "homepage_url": "https://fastapi.tiangolo.com",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/tiangolo/fastapi",
            "doc_paths": ["docs/en/docs/**/*.md"],
        },
        "doc_type": "guide",
        "latest_version": "0.115.0",
        "aliases": ["fastapi"],
        "versions": ["0.115.0"],
    },
    {
        "id": "/stripe/stripe-openapi",
        "org": "stripe",
        "project": "stripe-openapi",
        "name": "Stripe API",
        "description": "Stripe REST API (OpenAPI specification).",
        "homepage_url": "https://stripe.com/docs/api",
        "doc_source": {
            "type": "openapi",
            "url": "https://stripe.com/docs/api",
            "openapi_url": "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        },
        "doc_type": "reference",
        "latest_version": "2024-12-18",
        "aliases": ["stripe", "stripe-api"],
        "versions": ["2024-12-18"],
    },
]


def _aws_client(service: str, settings: Settings):
    return boto3.client(
        service,
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=Config(retries={"max_attempts": 3}),
    )


def seed_s3(settings: Settings, log) -> None:
    s3 = _aws_client("s3", settings)
    for bucket in (
        settings.s3_bucket_raw,
        settings.s3_bucket_markdown,
        settings.s3_bucket_artifacts,
    ):
        try:
            s3.create_bucket(Bucket=bucket)
            log.info("s3.create_bucket", bucket=bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                log.info("s3.bucket_exists", bucket=bucket)
            else:
                raise


def seed_sqs(settings: Settings, log) -> None:
    sqs = _aws_client("sqs", settings)
    for queue in (settings.sqs_queue_light, settings.sqs_queue_heavy):
        attrs = {"FifoQueue": "true", "ContentBasedDeduplication": "true"}
        sqs.create_queue(QueueName=queue, Attributes=attrs)
        log.info("sqs.create_queue", queue=queue)


def seed_libraries(log) -> None:
    engine = get_engine()
    with Session(engine) as session:
        for spec in SEED_LIBRARIES:
            existing = session.execute(
                select(Library).where(Library.id == spec["id"])
            ).scalar_one_or_none()
            if existing:
                log.info("library.exists", library_id=spec["id"])
                continue
            now = datetime.now(UTC)
            session.add(
                Library(
                    id=spec["id"],
                    name=spec["name"],
                    org=spec["org"],
                    project=spec["project"],
                    description=spec["description"],
                    homepage_url=spec["homepage_url"],
                    doc_source=spec["doc_source"],
                    trust_score=0.8,
                    doc_type=spec["doc_type"],
                    latest_version=spec["latest_version"],
                    created_at=now,
                    updated_at=now,
                )
            )
            for alias in spec["aliases"]:
                session.add(LibraryAlias(alias=alias, library_id=spec["id"]))
            for version in spec["versions"]:
                session.add(
                    LibraryVersion(
                        library_id=spec["id"],
                        version=version,
                        is_latest=(version == spec["latest_version"]),
                    )
                )
            log.info("library.created", library_id=spec["id"])
        session.commit()


def main() -> int:
    configure_logging()
    log = get_logger("dev_seed")
    settings = Settings()
    log.info("dev_seed.start", db=settings.database_url, aws=settings.aws_endpoint_url)
    seed_s3(settings, log)
    seed_sqs(settings, log)
    seed_libraries(log)
    log.info("dev_seed.done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
