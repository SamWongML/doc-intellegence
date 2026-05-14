# Shared Contracts

The seams between all three services. Load when a phase touches models, DB schema, or placeholder clients. Changing any of these is a breaking change.

## A. `Job` — SQS message body

```python
# packages/shared/doc_search_shared/models.py
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

class JobSource(BaseModel):
    type: Literal["github", "http_url", "openapi", "llms_full", "local_path"]
    url: str
    ref: Optional[str] = None
    doc_paths: list[str] = Field(default_factory=list)   # glob patterns
    openapi_url: Optional[str] = None

class Job(BaseModel):
    job_id: str                            # ULID
    library_id: str                        # e.g. "/vercel/next.js"
    version: Optional[str] = None
    source: JobSource
    mode: Literal["full", "incremental"] = "full"
    profile: Literal["light", "heavy"]
    requested_by: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: datetime
```

## B. `ProcessedDocument` — worker → RAG handoff

The worker does NOT chunk. The RAG system chunks + embeds.

```python
class CodeBlock(BaseModel):
    language: Optional[str] = None
    content: str

class ProcessedDocument(BaseModel):
    document_id: str                       # sha256(library_id + source_url)
    library_id: str
    version: Optional[str]
    source_url: str                        # canonical, no anchor
    title: str
    breadcrumbs: list[str]                 # ["App Router","Routing","Middleware"]
    doc_type: Literal["guide","reference","openapi_endpoint","tutorial","other"]
    language_tags: list[str] = Field(default_factory=list)
    markdown: str                          # CLEAN canonical body
    anchors: dict[str, str] = Field(default_factory=dict)
    # OpenAPI-only:
    openapi_spec: Optional[dict] = None
    openapi_summary: Optional[str] = None
    content_hash: str                      # sha256(normalized markdown)
    extracted_at: datetime
```

## C. `JobStatus` — RDS row updated by worker

```python
class JobStatus(BaseModel):
    job_id: str
    library_id: str
    state: Literal["queued","running","succeeded","failed","skipped"]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    docs_total: int = 0
    docs_processed: int = 0
    docs_reused: int = 0
    docs_failed: int = 0
    error: Optional[str] = None
    trace_id: Optional[str] = None
```

## D. Placeholder clients (the wiring contract)

When wiring later, ONLY these two files change. Method signatures are invariant.

```python
# packages/shared/doc_search_shared/clients/rag_embedding_client.py
from typing import Protocol
from pydantic import BaseModel
from doc_search_shared.models import ProcessedDocument

class IngestResult(BaseModel):
    ingested: int
    failed: int
    chunk_count: int
    document_ids: list[str]

class RagEmbeddingClient(Protocol):
    async def ingest_documents(
        self, documents: list[ProcessedDocument], *,
        library_id: str, version: str | None,
    ) -> IngestResult: ...
    async def tombstone_documents(
        self, document_ids: list[str], *,
        library_id: str, version: str | None,
    ) -> None: ...

class FakeRagEmbeddingClient:
    """Dev/tests: writes payload to S3 instead of calling real API."""
    async def ingest_documents(self, documents, *, library_id, version):
        ...  # TODO[wiring]: replace with httpx POST to RAG ingest endpoint
```

```python
# packages/shared/doc_search_shared/clients/rag_search_client.py
from typing import Protocol
from pydantic import BaseModel

class SearchHit(BaseModel):
    document_id: str
    chunk_id: str
    library_id: str
    version: str | None
    source_url: str
    title: str
    breadcrumbs: list[str]
    content: str                           # already reranked
    score: float
    section_id: str | None

class RagSearchClient(Protocol):
    async def hybrid_search(
        self, query: str, *,
        library_id: str, version: str | None = None,
        top_k: int = 20, filters: dict | None = None,
    ) -> list[SearchHit]: ...

class FakeRagSearchClient:
    """Dev/tests: returns canned fixtures."""
    ...  # TODO[wiring]
```

## E. Postgres schema (initial migration)

```sql
CREATE TABLE libraries (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  org             TEXT NOT NULL,
  project         TEXT NOT NULL,
  description     TEXT,
  homepage_url    TEXT,
  doc_source      JSONB,
  trust_score     REAL DEFAULT 0.5,
  doc_type        TEXT,
  latest_version  TEXT,
  last_indexed_at TIMESTAMPTZ,
  chunk_count     INTEGER DEFAULT 0,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE library_aliases (
  alias       TEXT NOT NULL,
  library_id  TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  PRIMARY KEY (alias, library_id)
);
CREATE INDEX ix_aliases_alias_lower ON library_aliases (LOWER(alias));

CREATE TABLE library_versions (
  library_id  TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
  version     TEXT NOT NULL,
  is_latest   BOOLEAN DEFAULT FALSE,
  indexed_at  TIMESTAMPTZ,
  PRIMARY KEY (library_id, version)
);

CREATE TABLE jobs (
  job_id         TEXT PRIMARY KEY,
  library_id     TEXT NOT NULL,
  version        TEXT,
  state          TEXT NOT NULL,   -- queued|running|succeeded|failed|skipped
  source         JSONB NOT NULL,
  mode           TEXT NOT NULL,
  profile        TEXT NOT NULL,
  docs_total     INTEGER DEFAULT 0,
  docs_processed INTEGER DEFAULT 0,
  docs_reused    INTEGER DEFAULT 0,
  docs_failed    INTEGER DEFAULT 0,
  error          TEXT,
  trace_id       TEXT,
  started_at     TIMESTAMPTZ,
  finished_at    TIMESTAMPTZ,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_jobs_library ON jobs (library_id, created_at DESC);

CREATE TABLE chunk_inventory (
  library_id    TEXT NOT NULL,
  version       TEXT,
  document_id   TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  source_url    TEXT,
  last_seen_job TEXT,
  updated_at    TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (library_id, version, document_id)
);
CREATE INDEX ix_inventory_hash ON chunk_inventory (library_id, content_hash);

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_libraries_name_trgm ON libraries USING GIN (name gin_trgm_ops);
CREATE INDEX ix_libraries_description_trgm ON libraries USING GIN (description gin_trgm_ops);
```
