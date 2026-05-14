"""Structured logging via structlog. Bind `trace_id` / `job_id` at entry points."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, level: str = "INFO", json: bool = False) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind(**kwargs: Any) -> None:
    """Bind context vars (e.g. ``trace_id``, ``job_id``) to all subsequent logs."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear() -> None:
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> Any:
    """Return a structlog bound logger. Returned type is structlog's own
    bound-logger; we type as ``Any`` to avoid pinning to internal generics."""
    return structlog.get_logger(name) if name else structlog.get_logger()


__all__ = ["bind", "clear", "configure_logging", "get_logger"]
