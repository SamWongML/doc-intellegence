"""Module-level structlog logger for the worker."""

from __future__ import annotations

from doc_search_shared.logging import get_logger

log = get_logger("doc_search_worker")

__all__ = ["log"]
