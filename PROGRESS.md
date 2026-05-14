# Doc-Search MCP — Progress

Per-session entry point. Read this first, then load only the active phase file + `docs/implementation/contracts.md` if needed.

## Status

| # | Phase | File | Status | Notes |
|---|-------|------|--------|-------|
| 0 | Foundation | [phase-0.md](docs/implementation/phase-0.md) | ☑ Done | shared models + alembic + dev stack; ruff/mypy/pytest green (2026-05-14) |
| 1 | Worker MVP (MD + OpenAPI) | [phase-1.md](docs/implementation/phase-1.md) | ☑ Done | services/worker: sources (github/openapi) + parsers + enrich + pipeline + SQS runner; ruff/mypy/pytest green (2026-05-14) |
| 2 | Worker HTML | [phase-2.md](docs/implementation/phase-2.md) | ☑ Done | services/worker: http_url + llms_txt sources, trafilatura+crawl4ai parsers, selectolax anchors, chrome strip, light→heavy requeue, Dockerfile.heavy; ruff/mypy/pytest green (2026-05-14) |
| 3 | Worker PDF/Office | [phase-3.md](docs/implementation/phase-3.md) | ☑ Done | services/worker: docling_parser (lazy import) + http_url content-type routing (PDF/Office light→requeue, heavy→docling) + Dockerfile.heavy adds docling weights; ruff/mypy/pytest green (2026-05-14) |
| 4 | Ingest API | [phase-4.md](docs/implementation/phase-4.md) | ☐ Not started | FastAPI, webhooks, scheduler |
| 5 | MCP Server | [phase-5.md](docs/implementation/phase-5.md) | ☐ Not started | resolve_library_id + query_docs |
| 6 | Hardening | [phase-6.md](docs/implementation/phase-6.md) | ☐ Not started | incremental, OTEL, IaC, CI/CD |

Legend: ☐ not started · ◐ in progress · ☑ done · ⊘ skipped

## How to use

1. Find next ☐ row; open that phase file.
2. Load `docs/implementation/contracts.md` only if the phase references shared models, schemas, or placeholder clients.
3. Load `docs/implementation/architecture.md` only on first session or when scoping infra.
4. After completing the phase: flip status to ☑, append a one-line note (commit SHA or date), commit.

## Build order

`0 → 1 → 2 → 4 → 5 → 6`. Phase 3 only if sources need it. Do not start Phase 5 before Phase 1 produces real `ProcessedDocument`s.

## Invariants (do not violate)

- Worker MUST NOT chunk, embed, or upsert vectors. It only emits `ProcessedDocument` + calls `RagEmbeddingClient`.
- `RagEmbeddingClient` / `RagSearchClient` method signatures are the wiring contract — never change them mid-build.
- All three services share Pydantic models via `packages/shared`.

## Wiring (post-internal-phases)

When the real RAG system is ready: edit only the two files in `packages/shared/doc_search_shared/clients/`. Grep `TODO[wiring]`.
