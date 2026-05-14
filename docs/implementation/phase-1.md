# Phase 1 — Worker MVP (Markdown + OpenAPI)

**Goal:** worker pulls jobs from SQS, fetches GitHub repo or OpenAPI URL, emits `ProcessedDocument` stream, calls `FakeRagEmbeddingClient.ingest_documents()` which writes JSONL to S3 (`artifacts/{job_id}.jsonl`).

This is the hardest phase. Nail the canonical output shape here — every parser plugs into the same shape.

**Needs:** `contracts.md` (Job, ProcessedDocument, JobStatus, clients).

## Deliverables

- `services/worker/Dockerfile` — Python 3.12-slim, no Chromium
- `doc_search_worker/__main__.py` — reads `WORKER_PROFILE=light|heavy`
- `doc_search_worker/runner.py`:
  - SQS long-poll: `WaitTimeSeconds=20`, `MaxNumberOfMessages=1`
  - parse `Job` → `pipeline.process_job(job)` → ack on success, NACK on retriable failure (DLQ catches >5)
  - heartbeat via `ChangeMessageVisibility` for long jobs
  - graceful SIGTERM: finish current message then exit 0 (needed for Fargate spot/scale-in)
- `doc_search_worker/pipeline.py` — orchestrates fetch → parse → enrich → handoff
- Sources:
  - `sources/github.py` — `pygit2` clone at `ref` into tempdir; apply `doc_paths` glob; yield `(path, bytes, source_url)`
  - `sources/openapi.py` — fetch JSON/YAML; deref `$ref` (`prance`); validate (`openapi-spec-validator`); yield one record per `(method, path)`
- Parsers:
  - `parsers/markdown.py` — `mistune` with frontmatter plugin → AST; extract YAML frontmatter → metadata; normalize (collapse blank lines, bullets to `-`, fenced code with lang hint); emit canonical Markdown
  - `parsers/openapi.py` — one endpoint → one `ProcessedDocument`. Body template:
    ```
    # POST /users/{id}
    > {summary}
    ## Parameters
    | name | in | type | required | description |
    ## Request body
    ## Responses
    ## Security
    ```
    `openapi_summary` = first 200 chars stub (real LLM in Phase 6); attach full deref'd spec to `openapi_spec`.
- Enrich:
  - `enrich/breadcrumbs.py` — walk heading tree; attach chain of preceding headings to each H2+/code/paragraph
  - `enrich/anchors.py` — generate kebab-case anchor id per heading; expose `anchors: {heading_text → anchor}`
  - `enrich/code_blocks.py` — detect language tag from fence info string; populate `language_tags`
- `hashing.py` — `content_hash = sha256(normalize_whitespace(markdown).encode())`
- `tests/` — sample MD fixtures, sample OpenAPI specs, golden outputs

## Worker behavior contract

Per `Job`:
1. Update `jobs` row → `state=running, started_at=now()`
2. Fetch source into tempdir/memory
3. For each input → parse → enrich → build `ProcessedDocument` → push to batch buffer
4. Flush in batches of **50** via `RagEmbeddingClient.ingest_documents(batch, library_id, version)`
5. Diff incoming `document_id`s vs `chunk_inventory` last set → **log only** (Phase 6 wires the skip)
6. On success: `jobs` → `state=succeeded`, counts, write `artifacts/{job_id}.jsonl` to S3
7. On failure: `jobs` → `state=failed, error=...`, raise (SQS retries)

## Dependencies

```toml
python = "^3.12"
boto3 = "^1.35"
aiobotocore = "^2.15"
httpx = "^0.27"
pydantic = "^2.9"
sqlalchemy = "^2.0"
asyncpg = "^0.29"
structlog = "^24.4"
mistune = "^3.0"
python-frontmatter = "^1.1"
pygit2 = "^1.15"
prance = "^23.6"
openapi-spec-validator = "^0.7"
tiktoken = "^0.8"
ulid-py = "^1.1"
```

## Acceptance

- `docker compose run worker` (profile=light) processes a tiny sample repo + OpenAPI URL; JSONL artifact lands in LocalStack S3.
- Round-trip: fixture repo with one MDX file → emitted `ProcessedDocument` has correct `title`, `breadcrumbs`, `anchors`, `content_hash`, canonical body.
- Petstore OpenAPI → N `ProcessedDocument`s where N == operation count; spot-check `openapi_spec` is fully deref'd.
- Worker survives SIGTERM mid-job: finishes current message then exits 0.
- DLQ catches messages failing 5 times.
- `pytest services/worker` green.

## Out of scope

HTML, PDF, Docling, real incremental skip (just log), real RAG API, Fargate deploy.

## DoD

End-to-end with sample repo + OpenAPI URL → JSONL in S3 · `pytest services/worker` green.
