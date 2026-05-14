"""SQLAlchemy table definitions compile against an in-memory SQLite DB."""

from __future__ import annotations

from doc_search_shared.db.tables import (
    Base,
    ChunkInventory,
    Job,
    Library,
    LibraryAlias,
    LibraryVersion,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def test_create_all_and_insert_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as s:
        s.add(
            Library(
                id="/vercel/next.js",
                name="Next.js",
                org="vercel",
                project="next.js",
                description="React framework.",
                trust_score=0.8,
                doc_type="guide",
                chunk_count=0,
            )
        )
        s.add(LibraryAlias(alias="next", library_id="/vercel/next.js"))
        s.add(
            LibraryVersion(
                library_id="/vercel/next.js",
                version="v15.1.0",
                is_latest=True,
            )
        )
        s.add(
            Job(
                job_id="job-1",
                library_id="/vercel/next.js",
                version="v15.1.0",
                state="queued",
                source={"type": "github", "url": "https://github.com/vercel/next.js"},
                mode="full",
                profile="light",
            )
        )
        s.add(
            ChunkInventory(
                library_id="/vercel/next.js",
                version="v15.1.0",
                document_id="doc-1",
                content_hash="h",
            )
        )
        s.commit()

        lib = s.execute(select(Library).where(Library.id == "/vercel/next.js")).scalar_one()
        assert lib.name == "Next.js"
        assert lib.doc_type == "guide"

        job = s.execute(select(Job).where(Job.job_id == "job-1")).scalar_one()
        assert job.source["type"] == "github"
