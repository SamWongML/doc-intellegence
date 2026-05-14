# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy workspace metadata so uv can resolve the shared package alongside worker.
COPY pyproject.toml uv.lock README.md ./
COPY packages/shared/pyproject.toml ./packages/shared/pyproject.toml
COPY services/worker/pyproject.toml ./services/worker/pyproject.toml

# Install uv, then materialize the locked deps for the worker only.
RUN pip install --no-cache-dir uv==0.8.17 \
 && uv sync --frozen --no-dev --package doc-search-worker

# Copy source.
COPY packages/shared ./packages/shared
COPY services/worker ./services/worker

# Phase-1 worker is light-profile: no Chromium, no Docling.
ENV WORKER_PROFILE=light \
    DOC_SEARCH_LOG_JSON=true \
    PATH="/app/.venv/bin:${PATH}"

ENTRYPOINT ["python", "-m", "doc_search_worker"]
