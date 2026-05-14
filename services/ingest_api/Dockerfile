# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Workspace metadata: uv resolves shared alongside ingest_api.
COPY pyproject.toml uv.lock README.md ./
COPY packages/shared/pyproject.toml ./packages/shared/pyproject.toml
COPY services/ingest_api/pyproject.toml ./services/ingest_api/pyproject.toml

RUN pip install --no-cache-dir uv==0.8.17 \
 && uv sync --frozen --no-dev --package doc-search-ingest

COPY packages/shared ./packages/shared
COPY services/ingest_api ./services/ingest_api

ENV DOC_SEARCH_LOG_JSON=true \
    INGEST_API_HOST=0.0.0.0 \
    INGEST_API_PORT=8080 \
    PATH="/app/.venv/bin:${PATH}"

EXPOSE 8080
ENTRYPOINT ["python", "-m", "doc_search_ingest"]
