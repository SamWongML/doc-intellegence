"""Shared fixtures for worker tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_repo_dir() -> Path:
    return FIXTURES / "sample_repo"


@pytest.fixture
def petstore_spec() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "petstore.json").read_text("utf-8"))
    return data
