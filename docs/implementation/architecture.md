# Architecture & Repo Layout

Load this only on first session or when scoping infra/repo structure. Per-phase files do not require it.

## Services

1. **Worker** (Service 1, ECS Fargate) — fetch/parse/normalize/enrich docs → emit `ProcessedDocument` + call `RagEmbeddingClient`. **Never chunks/embeds itself.**
2. **MCP Server** (Service 2, Fargate) — exposes `resolve_library_id` + `query_docs` to coding agents; calls `RagSearchClient`.
3. **Ingest API** (Service 3, Fargate or Lambda) — control plane: register/refresh/status, GitHub webhooks, EventBridge schedules.

## Diagram

```
  agents ──MCP──► MCP Server ──► RDS (registry)
                              └─► RAG search API (placeholder client)

  dev ──HTTP──► Ingest API ──► SQS (light|heavy FIFO)
                            └─► RDS (jobs)
                            └─► EventBridge Scheduler

  Worker pool ◄──SQS── pull
              ├─► S3 (raw, markdown, artifacts)
              ├─► RDS (job state, chunk_inventory)
              └─► RAG embedding API (placeholder client)
```

## AWS primitives

ECS Fargate · SQS FIFO · S3 · RDS Postgres 16 · ElastiCache Redis · EventBridge Scheduler · Secrets Manager · ECR · CloudWatch + X-Ray.

## Language / tooling

Python 3.12 everywhere. Pydantic v2. uv workspace (or Poetry path deps). One Docker image per service (worker has light + heavy variants).

## Repo layout

```
doc-search-mcp/
├── packages/shared/                 # imported by all services
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   └── doc_search_shared/
│       ├── models.py                # Pydantic: Job, ProcessedDocument, JobStatus
│       ├── ids.py                   # ULID, library_id parse/validate
│       ├── s3.py                    # path helpers
│       ├── db/{engine,tables}.py    # SQLAlchemy 2.0
│       ├── clients/
│       │   ├── rag_embedding_client.py   # PLACEHOLDER + Fake
│       │   └── rag_search_client.py      # PLACEHOLDER + Fake
│       ├── logging.py               # structlog + OTEL
│       └── settings.py              # pydantic-settings
│
├── services/
│   ├── worker/
│   │   ├── Dockerfile               # light (no Chromium)
│   │   ├── Dockerfile.heavy         # heavy (Crawl4AI + Chromium [+ Docling])
│   │   └── doc_search_worker/
│   │       ├── __main__.py · runner.py · pipeline.py · hashing.py
│   │       ├── sources/  {github, http_url, openapi, llms_txt}.py
│   │       ├── parsers/  {markdown, html_trafilatura, html_crawl4ai, openapi, docling_parser}.py
│   │       └── enrich/   {frontmatter, breadcrumbs, anchors, code_blocks}.py
│   │
│   ├── mcp_server/doc_search_mcp/
│   │   ├── __main__.py              # FastMCP stdio + streamable-http
│   │   ├── tools/ {resolve_library_id, query_docs}.py
│   │   ├── packer.py · registry.py
│   │
│   └── ingest_api/doc_search_ingest/
│       ├── app.py                   # FastAPI
│       ├── routes/ {libraries, jobs, webhooks_github}.py
│       └── scheduler.py             # EventBridge sync
│
├── infra/
│   ├── terraform/                   # (decide tf vs cdk in Phase 0)
│   └── docker-compose.dev.yml       # postgres, redis, localstack
│
├── scripts/ {dev_seed.py, smoke_e2e.sh, make_release.sh}
├── docs/    {ARCHITECTURE.md, CONTRACTS.md, RUNBOOKS.md}
├── .github/workflows/ {lint,test,deploy}.yml
├── pyproject.toml · ruff.toml · mypy.ini · README.md
```

## Local dev (single command)

```bash
docker compose -f infra/docker-compose.dev.yml up -d   # postgres, redis, localstack
uv sync
alembic -c packages/shared/alembic.ini upgrade head
python scripts/dev_seed.py

# Terminal 1: ingest API
uv run --package doc-search-ingest doc-search-ingest
# Terminal 2: worker
WORKER_PROFILE=light uv run --package doc-search-worker doc-search-worker
# Terminal 3: MCP
uv run --package doc-search-mcp doc-search-mcp --transport stdio

# Smoke
curl -X POST http://localhost:8080/libraries -d @scripts/sample_lib.json
npx @modelcontextprotocol/inspector uv run --package doc-search-mcp doc-search-mcp --transport stdio
```

## Glossary

- **library_id** — `/org/project` or `/org/project/version` (e.g. `/vercel/next.js/v15.1.0`).
- **document_id** — `sha256(library_id + source_url)`. Upsert key for the RAG system.
- **content_hash** — `sha256(normalize_whitespace(markdown))`. Used to skip unchanged docs.
- **ProcessedDocument** — canonical worker output (see `contracts.md` §B).
- **profile** — `light` | `heavy`; routes to the right worker queue/image.
- **section_id** — unique heading-section ID; used by MCP packer dedupe.

## Decision log

- **Fargate over Lambda for workers** — Lambda's 15-min cap + cold start cost on embedding clients makes it wrong for the loop.
- **Single language Python** — shared Pydantic + ecosystem (Trafilatura/Crawl4AI/Docling/prance). Swap MCP to TS only if RAG SDK forces it.
- **No pgvector in RDS** — vectors live in the existing RAG system. RDS holds metadata only.
- **Crawl4AI over Jina Reader** — self-hosted, zero per-page cost. Keep Jina as emergency flag.
- **Two worker images** — bundling Chromium everywhere triples size; two queues is worth it.
