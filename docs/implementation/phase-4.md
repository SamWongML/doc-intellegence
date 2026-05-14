# Phase 4 — Ingest Control API (Service 3)

**Goal:** the control plane. Developers POST to register/refresh libraries, query job status. GitHub webhooks auto-refresh on push. EventBridge runs scheduled refreshes.

**Needs:** `contracts.md` (Job + DB tables).

## Deliverables

- `services/ingest_api/Dockerfile`
- `doc_search_ingest/app.py` — FastAPI; auto-generated OpenAPI at `/openapi.json`
- `doc_search_ingest/__main__.py` — runnable as both uvicorn ASGI server and Lambda (`mangum`) handler

### Routes

| Method | Path | Behavior |
|--------|------|----------|
| POST   | `/libraries` | Validate `library_id` format; insert `libraries` + `library_aliases`; enqueue **full** job |
| POST   | `/libraries/{id}/refresh` | Enqueue **incremental** job (or `full` if `?mode=full`) |
| DELETE | `/libraries/{id}` | Soft-delete; enqueue tombstone job (wired in Phase 6) |
| GET    | `/libraries` | List with `last_indexed_at` |
| GET    | `/libraries/{id}` | Detail incl. recent jobs |
| GET    | `/jobs/{job_id}` | Status |
| POST   | `/webhooks/github` | Verify HMAC vs `GITHUB_WEBHOOK_SECRET`; on `push` touching `doc_paths` → enqueue refresh |

### Scheduler

- `doc_search_ingest/scheduler.py` — on `POST /libraries` with `refresh_schedule` in payload, create EventBridge Scheduler entry. Default: daily 06:00 UTC.

### AuthN / rate limit

- API key in `X-API-Key`, validated against Secrets Manager (or IAM if behind API Gateway).
- Per-API-key sliding window via Redis (default 60 req/min).

## Hosting

Run on Fargate behind ALB **or** Lambda + API Gateway. Lambda cheaper at low RPS. Don't lock the choice — keep `__main__.py` runnable as both.

## Acceptance

- `curl -X POST http://localhost:8080/libraries -d @sample_register.json` → library created, job enqueued, `job_id` returned; worker processes within seconds.
- Simulated signed GitHub push webhook → SQS depth jumps.
- EventBridge entry created in LocalStack when schedule provided.

## Out of scope

Multi-tenant auth/quotas. Public rate-limit policy.

## DoD

7 endpoints work · GitHub webhook triggers refresh · EventBridge schedule fires daily · `pytest services/ingest_api` green.
