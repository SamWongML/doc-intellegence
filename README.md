<div align="center">

# Doc-Search MCP

**Self-hosted documentation intelligence for AI coding agents.**

Ingest any docs — GitHub repos, OpenAPI specs, websites, PDFs — and serve them to agents via the [Model Context Protocol](https://modelcontextprotocol.io).

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/uv-workspace-DE5FE9?style=flat-square&logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/linted-ruff-FCC21B?style=flat-square)](https://docs.astral.sh/ruff/)
[![Mypy](https://img.shields.io/badge/typed-mypy-2A6DB2?style=flat-square)](https://mypy-lang.org)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev)
[![AWS](https://img.shields.io/badge/AWS-ECS%20%7C%20SQS%20%7C%20S3-FF9900?style=flat-square&logo=amazonaws&logoColor=white)](https://aws.amazon.com)

[Overview](#overview) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Services](#services) · [MCP Tools](#mcp-tools) · [Development](#development) · [Roadmap](#roadmap)

</div>

---

## Overview

Doc-Search MCP bridges the gap between raw documentation and AI-powered development workflows. It runs as three independent microservices on AWS Fargate:

- **Worker** crawls and parses docs from any source into structured, normalized documents
- **Ingest API** provides the control plane — register libraries, trigger refreshes, receive GitHub webhooks
- **MCP Server** exposes two tools (`resolve_library_id`, `query_docs`) that coding agents call to look up library docs in real time

The system deliberately keeps vector storage out of scope — it wires into your existing RAG system via a thin client interface, so it slots into any embedding/search backend without re-architecting it.

---

## Architecture

```
  AI Agents ──MCP──► MCP Server ─────────► PostgreSQL (library registry)
                          │
                          └──────────────► RAG Search API  ◄─── your backend

  Developers ──HTTP──► Ingest API ────────► SQS FIFO (light | heavy)
                            │              ► PostgreSQL (jobs)
                            └────────────► EventBridge Scheduler

  Worker Pool ◄──SQS── pull jobs
        ├──────────────────────────────── ► S3 (raw, markdown, artifacts)
        ├──────────────────────────────── ► PostgreSQL (job state)
        └──────────────────────────────── ► RAG Embedding API  ◄─── your backend
```

> **Light vs Heavy workers:** HTML extraction splits across two Docker images — `light` uses [Trafilatura](https://trafilatura.readthedocs.io/) (no Chromium), `heavy` uses [Crawl4AI](https://crawl4ai.com/) + headless Chromium + [Docling](https://ds4sd.github.io/docling/) for PDFs. Light jobs that fail are automatically requeued to heavy.

---

## Quick Start

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), Python 3.12+

```bash
# 1. Start infrastructure (Postgres, Redis, LocalStack)
docker compose -f infra/docker-compose.dev.yml up -d

# 2. Install dependencies and run migrations
uv sync
alembic -c packages/shared/alembic.ini upgrade head
python scripts/dev_seed.py
```

Then start each service in a separate terminal:

```bash
# Ingest API
uv run --package doc-search-ingest doc-search-ingest

# Worker (light profile)
WORKER_PROFILE=light uv run --package doc-search-worker doc-search-worker

# MCP Server
uv run --package doc-search-mcp doc-search-mcp --transport stdio
```

**Register a library and verify:**

```bash
# Register a library
curl -X POST http://localhost:8080/libraries \
  -H "Content-Type: application/json" \
  -d '{"library_id": "/vercel/next.js", "name": "Next.js", "source": {"type": "github", "url": "https://github.com/vercel/next.js"}}'

# Inspect MCP tools interactively
npx @modelcontextprotocol/inspector \
  uv run --package doc-search-mcp doc-search-mcp --transport stdio
```

---

## Services

### Worker (`services/worker`)

Fetches, parses, and normalizes documentation into `ProcessedDocument` objects, then hands them off to the RAG embedding client in batches of 50.

| Source type | Profile | Parser |
|---|---|---|
| `github` | light | Markdown (headings, code blocks, frontmatter) |
| `openapi` | light | [prance](https://github.com/RonnyPfannschmidt/prance) — one doc per operation |
| `http_url` | light | [Trafilatura](https://trafilatura.readthedocs.io/) |
| `http_url` | heavy | [Crawl4AI](https://crawl4ai.com/) (headless Chromium) |
| `http_url` (PDF/Office) | heavy | [Docling](https://ds4sd.github.io/docling/) |
| `llms_full` | light | `llms-full.txt` fast path, falling back to per-URL crawl |

### Ingest API (`services/ingest_api`)

FastAPI control plane — runs on Fargate or AWS Lambda (via Mangum). Provides:

- **`POST /libraries`** — register a library with source config
- **`POST /libraries/{id}/refresh`** — enqueue a fresh ingest job
- **`GET /jobs/{id}`** — poll job status
- **`POST /webhooks/github`** — auto-trigger on push events
- **EventBridge Scheduler** — cron-based periodic refreshes
- **Rate limiting** — Redis sliding-window (falls back to in-memory)
- **Auth** — `X-API-Key` header

### MCP Server (`services/mcp_server`)

[FastMCP](https://github.com/jlowin/fastmcp) server exposing two tools over `stdio` or streamable HTTP. Backed by a two-layer cache (in-process + Redis) over the PostgreSQL library registry.

---

## MCP Tools

### `resolve_library_id`

Resolves a free-form library name to one or more canonical `library_id`s using a four-stage fallback:

| Stage | Example query | Confidence |
|---|---|---|
| Exact ID | `/vercel/next.js` | `1.00` |
| Exact alias | `next.js` | `0.95` |
| Version-aware | `next.js@15.1.0` | `0.90` |
| Fuzzy (`pg_trgm`) | `nextjs routing` | `0.70 × similarity + 0.30 × trust` |

```json
// Example response
{
  "query": "next.js",
  "matches": [
    {
      "id": "/vercel/next.js",
      "name": "Next.js",
      "latest_version": "v15.1.0",
      "confidence": 0.95
    }
  ],
  "guidance": "Matched by alias to /vercel/next.js (confidence 0.95). Use this id with query_docs."
}
```

### `query_docs`

Runs hybrid search over a registered library and packs results into a configurable token budget.

```json
// Example call
{
  "library_id": "/vercel/next.js",
  "topic": "app router data fetching",
  "token_budget": 6000,
  "version": "v15.1.0"
}
```

Returns ranked document chunks with metadata — breadcrumbs, anchors, source URLs, language tags — truncated to fit the token budget.

---

## Development

### Repo layout

```
doc-search-mcp/
├── packages/shared/          # Shared Pydantic models, DB engine, placeholder RAG clients
├── services/
│   ├── worker/               # Fetch → parse → enrich pipeline
│   ├── ingest_api/           # FastAPI control plane
│   └── mcp_server/           # FastMCP server (resolve + query tools)
├── infra/
│   └── docker-compose.dev.yml
├── scripts/                  # dev_seed.py, smoke tests
└── docs/implementation/      # Phase specs and architecture notes
```

### Running tests

```bash
uv run pytest
```

All services share a single pytest configuration at the repo root. Tests use `moto` for AWS mocking, `fakeredis` for Redis, and `respx` for HTTP.

### Code quality

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy .                # type check
```

Pre-commit hooks run all three automatically on commit.

### Wiring to your RAG backend

The worker and MCP server talk to your RAG system through two thin client interfaces in `packages/shared/doc_search_shared/clients/`. Both ship with `Fake*` implementations for local development. To connect a real backend, edit only these two files:

| File | Interface |
|---|---|
| `rag_embedding_client.py` | `ingest_documents(docs, library_id, version)` |
| `rag_search_client.py` | `hybrid_search(query, library_id, version, top_k)` |

Search for `TODO[wiring]` to find every callsite.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API framework | FastAPI + Mangum (Lambda adapter) |
| MCP framework | FastMCP (stdio + streamable HTTP) |
| Data validation | Pydantic v2 |
| Database | PostgreSQL 16 (RDS) via SQLAlchemy 2.0 + Alembic |
| Cache / rate limit | Redis 7 (ElastiCache) |
| Queue | AWS SQS FIFO (light + heavy) |
| Object storage | AWS S3 |
| Scheduling | AWS EventBridge Scheduler |
| HTML extraction | Trafilatura (light) · Crawl4AI + Chromium (heavy) |
| PDF / Office | Docling |
| Package manager | uv (workspace) |
| Linting / formatting | Ruff |
| Type checking | Mypy |
| Testing | pytest + pytest-asyncio · moto · fakeredis · respx |

---

## Roadmap

| Phase | Description | Status |
|---|---|---|
| 0 | Shared models, DB schema, dev stack | ✅ Done |
| 1 | Worker — GitHub + OpenAPI sources | ✅ Done |
| 2 | Worker — HTML (light + heavy) | ✅ Done |
| 3 | Worker — PDF / Office via Docling | ✅ Done |
| 4 | Ingest API (FastAPI + SQS + webhooks) | ✅ Done |
| 5 | MCP Server (resolve + query + cache) | ✅ Done |
| 6 | Hardening — incremental ingest, OTEL, IaC, CI/CD | 🔲 Next |

---

<div align="center">

Built with Python 3.12 · FastMCP · FastAPI · PostgreSQL · AWS

</div>
