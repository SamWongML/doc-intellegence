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


@pytest.fixture
def html_fixtures_dir() -> Path:
    return FIXTURES / "html"


@pytest.fixture
def nextjs_html(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "nextjs_middleware.html").read_text("utf-8")


@pytest.fixture
def stripe_html(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "stripe_intro.html").read_text("utf-8")


@pytest.fixture
def spa_html(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "spa_empty.html").read_text("utf-8")


@pytest.fixture
def llms_full_text(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "llms-full.txt").read_text("utf-8")


@pytest.fixture
def llms_index_text(html_fixtures_dir: Path) -> str:
    return (html_fixtures_dir / "llms.txt").read_text("utf-8")
