"""X-API-Key validation against a comma-separated allowlist.

In production the allowlist comes from Secrets Manager (resolved at app
startup or rotated via a sidecar). Here we keep the contract simple: the
``Settings.ingest_api_keys`` env var is the source of truth.
"""

from __future__ import annotations

from doc_search_shared.settings import Settings
from fastapi import Header, HTTPException, status

_NO_AUTH_PRINCIPAL = "dev"


def parse_keys(raw: str) -> set[str]:
    return {k.strip() for k in raw.split(",") if k.strip()}


def authenticate(
    x_api_key: str | None,
    settings: Settings,
) -> str:
    """Return the principal id (the API key string), or raise 401.

    When ``settings.ingest_api_keys`` is empty, auth is disabled and the
    principal is the sentinel ``"dev"``.
    """
    allowed = parse_keys(settings.ingest_api_keys)
    if not allowed:
        return _NO_AUTH_PRINCIPAL
    if not x_api_key or x_api_key not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
        )
    return x_api_key


async def authenticate_dep(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency wrapper around :func:`authenticate`.

    Pulls ``Settings`` from the process-wide cache so it stays a pure callable
    (easy to override in tests via ``app.dependency_overrides``).
    """
    return authenticate(x_api_key, Settings())


__all__ = ["authenticate", "authenticate_dep", "parse_keys"]
