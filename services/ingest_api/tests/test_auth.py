"""X-API-Key validation."""

from __future__ import annotations

import pytest
from doc_search_ingest.auth import authenticate
from doc_search_shared.settings import Settings
from fastapi import HTTPException


def _settings(keys: str = "") -> Settings:
    return Settings(
        ingest_api_keys=keys,
        aws_endpoint_url=None,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def test_authenticate_disabled_when_no_keys() -> None:
    principal = authenticate(None, _settings(""))
    assert principal == "dev"


def test_authenticate_accepts_valid_key() -> None:
    principal = authenticate("abc", _settings("abc, def"))
    assert principal == "abc"


def test_authenticate_rejects_missing_key() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate(None, _settings("abc"))
    assert exc.value.status_code == 401


def test_authenticate_rejects_unknown_key() -> None:
    with pytest.raises(HTTPException) as exc:
        authenticate("wrong", _settings("abc, def"))
    assert exc.value.status_code == 401
