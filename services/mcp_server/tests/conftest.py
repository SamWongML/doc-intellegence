"""Shared fixtures for the MCP server test suite.

Three libraries seed every fixture so resolve_library_id has a meaningful
fuzzy/exact split: Next.js (versioned), FastAPI (unversioned), and a Stripe
OpenAPI bundle that doubles as a "wrong neighbourhood" decoy for fuzzy tests.
"""

from __future__ import annotations

import pytest
from doc_search_mcp.registry import LibraryRecord, MemoryBackend, Registry


@pytest.fixture
def libraries() -> list[LibraryRecord]:
    return [
        LibraryRecord(
            id="/vercel/next.js",
            name="Next.js",
            description="The React framework for the web.",
            doc_type="guide",
            latest_version="v15.1.0",
            trust_score=0.9,
            chunk_count=1234,
            available_versions=["v15.1.0", "v14.2.0"],
        ),
        LibraryRecord(
            id="/tiangolo/fastapi",
            name="FastAPI",
            description="Modern, high-performance web framework for Python APIs.",
            doc_type="guide",
            latest_version="0.115.0",
            trust_score=0.85,
            chunk_count=987,
            available_versions=["0.115.0"],
        ),
        LibraryRecord(
            id="/stripe/stripe-openapi",
            name="Stripe API",
            description="Stripe REST API (OpenAPI specification).",
            doc_type="reference",
            latest_version="2024-12-18",
            trust_score=0.7,
            chunk_count=456,
            available_versions=["2024-12-18"],
        ),
    ]


@pytest.fixture
def aliases() -> dict[str, list[str]]:
    return {
        "next": ["/vercel/next.js"],
        "nextjs": ["/vercel/next.js"],
        "next.js": ["/vercel/next.js"],
        "fastapi": ["/tiangolo/fastapi"],
        "stripe": ["/stripe/stripe-openapi"],
        "stripe-api": ["/stripe/stripe-openapi"],
    }


@pytest.fixture
def registry(
    libraries: list[LibraryRecord],
    aliases: dict[str, list[str]],
) -> Registry:
    backend = MemoryBackend(libraries, aliases=aliases)
    return Registry(backend)
