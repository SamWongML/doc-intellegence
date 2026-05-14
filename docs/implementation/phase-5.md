# Phase 5 — MCP Server (Service 2)

**Goal:** expose `resolve_library_id` + `query_docs` to coding agents. Registry-backed (Postgres) + RAG hybrid search (placeholder client).

**Needs:** `contracts.md` (DB tables + `RagSearchClient` shape). Do NOT start before Phase 1 emits real `ProcessedDocument`s.

## Deliverables

- `services/mcp_server/Dockerfile`
- `doc_search_mcp/__main__.py`:
  - FastMCP server, both `stdio` and `streamable-http` transports
  - `--transport stdio|http` flag
- `tools/resolve_library_id.py`:
  - signature: `resolve_library_id(query: str, max_results: int = 5) -> dict`
  - resolution order: exact ID → exact alias → version-aware parse → pg_trgm fuzzy on name + description
  - score blend: `0.7 * trgm_similarity + 0.3 * trust_score`, cap at `max_results`, hard ceiling 10
  - response: `matches[]` each with `id, name, description, latest_version, available_versions, trust_score, chunk_count, doc_type, confidence` + top-level `guidance` string
- `tools/query_docs.py`:
  - signature: `query_docs(library_id, topic, token_budget=6000, version=None, include_examples=True) -> dict`
  - validate `library_id` exists; if not → guidance error pointing to `resolve_library_id`
  - call `RagSearchClient.hybrid_search(query=topic, library_id, version, top_k=20)`
  - feed results to `packer.py`
- `packer.py` — token-budget packer:
  - always include top-scored chunk (truncate if needed, keep ≥200 token headroom)
  - dedupe by `section_id`
  - if `include_examples=False`, strip fenced code blocks before counting
  - greedy with "keep scanning" (don't stop at first overflow)
  - tokenize with `tiktoken.cl100k_base`
- `registry.py` — async Postgres queries used by both tools; in-process LRU (10 min TTL) over Redis (5 min TTL)
- `tests/`:
  - `resolve_library_id`: exact / alias / version-aware / fuzzy / ambiguous — table-driven
  - `query_docs`:
    - budget=2000 with 10 candidates totaling 8000 tokens → ~2000 tokens returned
    - budget=200 with one 5000-token chunk → truncated top chunk, `truncated=true`
    - `include_examples=False` strips code

## Transport details

- **stdio:** individual dev installs. Ship via PyPI as `doc-search-mcp` → `uvx doc-search-mcp`.
- **streamable-http:** team installs. Fargate behind ALB with sticky sessions. CORS configured. Auth via OAuth or API key (decided at wiring).

## Acceptance

- `mcp inspector` or Claude Desktop connect to stdio server → both tools list.
- `resolve_library_id("nextjs")` → Next.js as top match, confidence ≥ 0.9.
- `query_docs("/vercel/next.js", "middleware authentication", token_budget=4000)` → ≤4000 tokens, dedup'd by section, top chunk always present.
- budget=200 vs 2000-token top chunk → truncated top chunk + `truncated=true`.
- `pytest services/mcp_server` green; integration tests use `FakeRagSearchClient` with known fixtures.

## Out of scope

`get_endpoint_spec` tool (defer to Phase 6).

## DoD

Both tools work end-to-end against `FakeRagSearchClient` · HTTP transport runs behind ALB · `pytest services/mcp_server` green.
