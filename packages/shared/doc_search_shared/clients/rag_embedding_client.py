"""Worker → RAG embedding handoff.

The ``RagEmbeddingClient`` Protocol is the wiring contract. Signatures here
MUST NOT change once services depend on them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from ..logging import get_logger
from ..models import ProcessedDocument

log = get_logger(__name__)


class IngestResult(BaseModel):
    ingested: int
    failed: int
    chunk_count: int
    document_ids: list[str]


@runtime_checkable
class RagEmbeddingClient(Protocol):
    async def ingest_documents(
        self,
        documents: list[ProcessedDocument],
        *,
        library_id: str,
        version: str | None,
    ) -> IngestResult: ...

    async def tombstone_documents(
        self,
        document_ids: list[str],
        *,
        library_id: str,
        version: str | None,
    ) -> None: ...


class FakeRagEmbeddingClient:
    """Dev/test stub. Returns realistic-shaped fake results; does not network.

    TODO[wiring]: Replace with the real httpx-based client that POSTs to the
    RAG ingest endpoint. Only edit this file when wiring.
    """

    def __init__(self) -> None:
        self.ingested: list[ProcessedDocument] = []
        self.tombstoned: list[str] = []

    async def ingest_documents(
        self,
        documents: list[ProcessedDocument],
        *,
        library_id: str,
        version: str | None,
    ) -> IngestResult:
        self.ingested.extend(documents)
        ids = [d.document_id for d in documents]
        log.info(
            "fake.ingest_documents",
            library_id=library_id,
            version=version,
            count=len(ids),
        )
        # Pretend each doc averages 4 chunks.
        return IngestResult(
            ingested=len(ids),
            failed=0,
            chunk_count=len(ids) * 4,
            document_ids=ids,
        )

    async def tombstone_documents(
        self,
        document_ids: list[str],
        *,
        library_id: str,
        version: str | None,
    ) -> None:
        self.tombstoned.extend(document_ids)
        log.info(
            "fake.tombstone_documents",
            library_id=library_id,
            version=version,
            count=len(document_ids),
        )


__all__ = ["FakeRagEmbeddingClient", "IngestResult", "RagEmbeddingClient"]
