"""GitHub webhook signature verification + push-event handling.

The webhook contract: GitHub POSTs to ``/webhooks/github`` with the JSON
event body and an ``X-Hub-Signature-256: sha256=<hex>`` header. We HMAC the
raw body with ``DOC_SEARCH_GITHUB_WEBHOOK_SECRET`` and require equality.

On a verified ``push`` event we look up libraries whose ``doc_source.url``
matches the pushed repo, glob-match the changed paths against
``doc_source.doc_paths``, and enqueue an incremental refresh per match.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
from typing import Any

from doc_search_shared.db.tables import Library
from doc_search_shared.models import JobSource
from sqlalchemy import select
from sqlalchemy.orm import Session


def verify_signature(*, body: bytes, header: str | None, secret: str) -> bool:
    """Constant-time HMAC verification.

    Returns ``True`` when the secret is unset *and* no header is provided
    (dev mode); never returns ``True`` when a header is provided but the
    secret is missing.
    """
    if not secret:
        return header is None
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    provided = header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def extract_push_paths(event: dict[str, Any]) -> list[str]:
    """Pull the union of added/modified/removed paths from a push payload."""
    paths: set[str] = set()
    for commit in event.get("commits", []) or []:
        for bucket in ("added", "modified", "removed"):
            for p in commit.get(bucket, []) or []:
                if isinstance(p, str):
                    paths.add(p)
    return sorted(paths)


def normalize_repo_url(url: str) -> str:
    """Strip protocol/owner/repo down to a comparable form ``owner/repo``.

    Accepts:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - git@github.com:owner/repo.git
    Returns ``owner/repo`` (lowercased), or the original if unrecognized.
    """
    candidate = url.strip().lower()
    candidate = candidate.removesuffix(".git")
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "git@github.com:",
        "ssh://git@github.com/",
    ):
        if candidate.startswith(prefix):
            return candidate[len(prefix) :].strip("/")
    return candidate


def matches_doc_paths(changed: list[str], doc_paths: list[str]) -> bool:
    if not doc_paths:
        return True  # no filter → any push matches
    if not changed:
        return False
    for pattern in doc_paths:
        for path in changed:
            if fnmatch.fnmatch(path, pattern):
                return True
    return False


def libraries_for_repo(session: Session, *, repo_full_name: str) -> list[Library]:
    """Return libraries whose ``doc_source.url`` resolves to ``repo_full_name``."""
    rows = session.execute(select(Library)).scalars().all()
    matches = []
    for row in rows:
        ds = row.doc_source or {}
        if ds.get("type") != "github":
            continue
        url = ds.get("url") or ""
        if normalize_repo_url(url) == repo_full_name:
            matches.append(row)
    return matches


def job_source_from_library(library: Library) -> JobSource:
    """Build a ``JobSource`` from a stored ``Library.doc_source``."""
    raw = dict(library.doc_source or {})
    return JobSource.model_validate(raw)


__all__ = [
    "extract_push_paths",
    "job_source_from_library",
    "libraries_for_repo",
    "matches_doc_paths",
    "normalize_repo_url",
    "verify_signature",
]
