"""Entry point for the Doc-Search MCP server.

Two transports:

* ``--transport stdio`` (default): used by ``uvx doc-search-mcp`` from local
  IDE configs (Claude Desktop, mcp inspector, etc.).
* ``--transport http``: streamable-HTTP, used behind ALB on Fargate. The same
  process tree, just a different listener.

Tool implementations live in :mod:`doc_search_mcp.tools`. The thin wrappers
below adapt them to the FastMCP signature (``Context``-aware) and shovel the
:class:`Resources` bundle through ``request_context.lifespan_context``.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from doc_search_shared.logging import configure_logging, get_logger
from doc_search_shared.settings import Settings
from mcp.server.fastmcp import Context, FastMCP

from .deps import Resources, build_resources
from .tools.query_docs import query_docs as _query_docs_impl
from .tools.resolve_library_id import resolve_library_id as _resolve_library_id_impl

log = get_logger(__name__)


@asynccontextmanager
async def _default_lifespan(_server: FastMCP) -> AsyncIterator[Resources]:
    resources = await build_resources()
    log.info("mcp.start")
    try:
        yield resources
    finally:
        await resources.aclose()
        log.info("mcp.stop")


def create_server(
    *,
    lifespan: Any = _default_lifespan,
    resources: Resources | None = None,
) -> FastMCP:
    """Build a FastMCP server with both tools registered.

    Pass an explicit ``resources`` bundle (e.g. in tests) to bypass the
    Postgres+Redis wiring; in that case the ``lifespan`` argument is ignored.
    """
    if resources is not None:

        @asynccontextmanager
        async def _fixed_lifespan(_server: FastMCP) -> AsyncIterator[Resources]:
            yield resources

        lifespan = _fixed_lifespan

    mcp = FastMCP("doc-search", lifespan=lifespan)

    def _resources(ctx: Context[Any, Any]) -> Resources:
        return ctx.request_context.lifespan_context  # type: ignore[no-any-return]

    @mcp.tool(
        name="resolve_library_id",
        description=(
            "Resolve a free-form library name (e.g. 'next.js') to one or more "
            "registered library IDs. Returns matches[] sorted by confidence "
            "plus a guidance string. Always call this before query_docs."
        ),
    )
    async def resolve_library_id(
        query: str,
        ctx: Context[Any, Any],
        max_results: int = 5,
    ) -> dict[str, Any]:
        return await _resolve_library_id_impl(
            query,
            registry=_resources(ctx).registry,
            max_results=max_results,
        )

    @mcp.tool(
        name="query_docs",
        description=(
            "Hybrid-search a library for ``topic`` and return chunks packed "
            "into ``token_budget``. Validate library_id with resolve_library_id "
            "first. Set include_examples=False to strip code blocks."
        ),
    )
    async def query_docs(
        library_id: str,
        topic: str,
        ctx: Context[Any, Any],
        token_budget: int = 6000,
        version: str | None = None,
        include_examples: bool = True,
    ) -> dict[str, Any]:
        res = _resources(ctx)
        return await _query_docs_impl(
            library_id,
            topic,
            registry=res.registry,
            search=res.search,
            token_budget=token_budget,
            version=version,
            include_examples=include_examples,
        )

    return mcp


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-search-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("DOC_SEARCH_MCP_TRANSPORT", "stdio"),
        help="MCP transport. stdio for IDE installs; http for Fargate.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DOC_SEARCH_MCP_HOST", "0.0.0.0"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DOC_SEARCH_MCP_PORT", "8080")),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    settings = Settings()
    configure_logging(level=settings.log_level, json=settings.log_json)

    server = create_server()

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        # FastMCP reads host/port from the underlying Settings; expose them
        # via env so users can override either way.
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())


__all__ = ["create_server", "main"]
