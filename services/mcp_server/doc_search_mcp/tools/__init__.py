"""MCP tool implementations.

Each tool function is plain ``async def`` taking a :class:`Registry` (and the
:class:`RagSearchClient` for ``query_docs``) so unit tests can exercise the
full logic without a FastMCP server.
"""

from __future__ import annotations

from .query_docs import query_docs
from .resolve_library_id import resolve_library_id

__all__ = ["query_docs", "resolve_library_id"]
