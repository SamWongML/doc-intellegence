# Phase 6 — Hardening

**Goal:** prototype → operable system.

**Needs:** all prior phases.

## Deliverables (priority order)

### 1. Incremental refresh (real)

- Every job writes `chunk_inventory(document_id, content_hash, source_url, last_seen_job)`.
- Start of `incremental` job: load prior inventory; for each new `ProcessedDocument`, if `content_hash` matches existing → skip embedding call, just update `last_seen_job`.
- End of job: rows whose `last_seen_job ≠ current_job` → enqueue tombstone via `RagEmbeddingClient.tombstone_documents`.

### 2. LLM-generated OpenAPI summaries

- Replace stub in `parsers/openapi.py` with one-shot LLM call. Gate behind `OPENAPI_SUMMARY_MODEL` env.
- Cache by `sha256(endpoint_spec)` in Postgres so refreshes don't re-bill.

### 3. `get_endpoint_spec` MCP tool

- Reads `ProcessedDocument.openapi_spec` for one `document_id` (via RAG get-by-id or new placeholder method).
- Returns full deref'd spec.

### 4. OpenTelemetry

- Trace propagation: API → SQS message attribute → worker → ingest call.
- Spans for fetch / parse / enrich / ingest.
- Export to CloudWatch via OTEL Collector sidecar. X-Ray Service Map shows all three services.

### 5. CloudWatch dashboards + alarms

- Dashboard: SQS depth · worker task count · job p95 by source type · `docs_reused` ratio · `query_docs` p95.
- Alarms: DLQ depth ≥ 1 · job failure rate ≥ 10% over 15 min · `query_docs` p95 > 1.5s.

### 6. Infrastructure as Code

- All AWS resources in Terraform (recommended) or AWS CDK Python.
- Workspaces: `dev`, `staging`, `prod`.

### 7. CI/CD

- GitHub Actions: on push to `main` → build 3 Docker images → push to ECR → `terraform apply` (manual approval for prod).

### 8. Security pass

- Workers: least-privilege IAM on S3/SQS/RDS/Secrets.
- Ingest API: Secrets Manager for GitHub webhook secret + API keys.
- MCP HTTP: TLS via ALB ACM cert; optional WAF.

### 9. Runbooks (`docs/RUNBOOKS.md`)

- "Worker stuck" → check ECS task logs, force replace.
- "DLQ has messages" → inspect, fix, replay via re-enqueue script.
- "query_docs slow" → check Redis hit rate, RAG p95, packer time.

## Acceptance

- Refresh on unchanged source → `docs_reused / docs_total > 0.95`.
- Adding one OpenAPI endpoint → only that endpoint gets a new ingest call.
- Single `job_id` traces end-to-end across services in X-Ray.
- `terraform plan` clean against deployed `dev`; tear-down + reapply yields same infra.

## DoD

≥95% reuse on unchanged refresh · cross-service trace in X-Ray · all infra in Terraform · runbooks written.
