"""Smoke test for ``create_server``: tools register and the FastMCP instance
exposes the expected metadata. Full end-to-end transport tests run separately
(stdio over a subprocess) and are out of scope for unit tests."""

from __future__ import annotations

import pytest
from doc_search_mcp.__main__ import create_server
from doc_search_mcp.deps import Resources
from doc_search_mcp.registry import Registry
from doc_search_shared.clients.rag_search_client import FakeRagSearchClient
from doc_search_shared.settings import Settings


@pytest.mark.asyncio
async def test_create_server_lists_both_tools(registry: Registry) -> None:
    resources = Resources(
        registry=registry,
        search=FakeRagSearchClient(),
        settings=Settings(),
    )
    server = create_server(resources=resources)
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == {"resolve_library_id", "query_docs"}
