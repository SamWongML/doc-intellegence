"""Breadcrumb derivation.

* ``breadcrumbs_from_path`` produces the document-level crumb chain expected
  by `ProcessedDocument.breadcrumbs`, derived from the doc's folder path.
* ``section_breadcrumbs`` walks an ordered (level, text) heading list and
  returns, per heading index, the chain of preceding ancestor headings.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePosixPath


def breadcrumbs_from_path(rel_path: str | PurePosixPath) -> list[str]:
    """``docs/app-router/routing/middleware.mdx`` → ``["App Router", "Routing"]``.

    Drops the filename and a leading ``docs``/``doc`` segment if present.
    """
    parts = list(PurePosixPath(str(rel_path)).parts[:-1])
    if parts and parts[0].lower() in {"docs", "doc"}:
        parts = parts[1:]
    return [_humanize(p) for p in parts if p]


def section_breadcrumbs(
    headings: Iterable[tuple[int, str]],
) -> dict[int, list[str]]:
    """For each heading index, return the chain of ancestor heading texts
    (level-strictly-less). Excludes the heading itself."""
    stack: list[tuple[int, str]] = []
    out: dict[int, list[str]] = {}
    for idx, (level, text) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        out[idx] = [t for _, t in stack]
        stack.append((level, text))
    return out


def _humanize(segment: str) -> str:
    cleaned = segment.replace("_", "-")
    return " ".join(word.capitalize() for word in cleaned.split("-") if word)


__all__ = ["breadcrumbs_from_path", "section_breadcrumbs"]
