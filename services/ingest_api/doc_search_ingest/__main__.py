"""Entry point: ``python -m doc_search_ingest`` runs uvicorn.

The same module exposes a ``handler`` symbol for AWS Lambda via Mangum, so
the deployable artifact is identical between Fargate and Lambda hosting.
"""

from __future__ import annotations

import os

from .app import create_app

app = create_app()

# Lambda entry: ``mangum`` wraps the ASGI app. Module-level so SAM / CDK can
# point at ``doc_search_ingest.__main__.handler``.
try:
    from mangum import Mangum

    handler = Mangum(app, lifespan="off")
except ImportError:  # pragma: no cover - mangum optional locally
    handler = None  # type: ignore[assignment]


def main() -> int:
    import uvicorn

    host = os.environ.get("INGEST_API_HOST", "0.0.0.0")
    port = int(os.environ.get("INGEST_API_PORT", "8080"))
    uvicorn.run(
        "doc_search_ingest.__main__:app",
        host=host,
        port=port,
        log_level=os.environ.get("DOC_SEARCH_LOG_LEVEL", "info").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
