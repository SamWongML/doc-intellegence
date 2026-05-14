# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages/shared/pyproject.toml ./packages/shared/pyproject.toml
COPY services/mcp_server/pyproject.toml ./services/mcp_server/pyproject.toml

RUN pip install --no-cache-dir uv==0.8.17 \
 && uv sync --frozen --no-dev --package doc-search-mcp-server

COPY packages/shared ./packages/shared
COPY services/mcp_server ./services/mcp_server

# Pre-warm the tiktoken cl100k_base encoding so first-request latency is fast
# and the server keeps working on networks where openaipublic blob is blocked.
RUN /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

ENV DOC_SEARCH_LOG_JSON=true \
    DOC_SEARCH_MCP_TRANSPORT=http \
    DOC_SEARCH_MCP_HOST=0.0.0.0 \
    DOC_SEARCH_MCP_PORT=8080 \
    PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080
ENTRYPOINT ["python", "-m", "doc_search_mcp"]
