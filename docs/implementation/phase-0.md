# Phase 0 — Foundation

**Goal:** repo + shared models + local dev stack runnable in one command + placeholder clients returning realistic fakes.

**Needs:** `contracts.md` (models + schema) and `architecture.md` (repo layout).

## Deliverables

- Workspace `pyproject.toml` (uv workspaces or Poetry path deps)
- `packages/shared/doc_search_shared/`:
  - `models.py` — every Pydantic model from `contracts.md` §A–C
  - `ids.py` — ULID gen; `library_id` parse/validate (`/org/project[/version]`)
  - `settings.py` — `pydantic-settings` reading env
  - `db/tables.py` — SQLAlchemy 2.0 for tables in `contracts.md` §E
  - `clients/rag_embedding_client.py` + `clients/rag_search_client.py` — Protocols + `Fake*` impls
  - `s3.py` — `raw_path`, `markdown_path`, `artifact_path`
  - `logging.py` — `structlog` with `trace_id` + `job_id` binding
- `packages/shared/migrations/` — Alembic init + first migration matching `contracts.md` §E
- `infra/docker-compose.dev.yml`:
  - Postgres 16 (runs `alembic upgrade head` on startup)
  - Redis 7
  - LocalStack (S3 + SQS only)
- `scripts/dev_seed.py` — seed 3 libraries + create SQS queues + S3 buckets
- `ruff.toml`, `mypy.ini`, pre-commit
- `.github/workflows/` — lint + typecheck + test on push
- Add pytest marker `wiring` (used Phase 6+ for tests against real RAG)

## Acceptance

- `docker compose -f infra/docker-compose.dev.yml up` → Postgres + Redis + LocalStack with schema migrated and queues/buckets created.
- `python scripts/dev_seed.py` populates 3 libraries.
- `pytest packages/shared` passes (model round-trips).
- `ruff check .` and `mypy packages/shared` clean.

## Out of scope

No service implementations. No AWS deployment. No real RAG calls.

## DoD

`docker compose up` works · `pytest packages/shared` green · CI lint/typecheck green.
