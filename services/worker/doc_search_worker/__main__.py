"""Entry point: ``python -m doc_search_worker``.

Reads ``WORKER_PROFILE=light|heavy`` from env (via shared Settings) and runs
the SQS poll loop until SIGTERM/SIGINT, then exits cleanly.
"""

from __future__ import annotations

import asyncio

from doc_search_shared.logging import configure_logging
from doc_search_shared.settings import Settings

from .runner import Runner, install_signal_handlers


def main() -> int:
    settings = Settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    runner = Runner.from_settings(settings)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    install_signal_handlers(runner, loop)
    try:
        loop.run_until_complete(runner.run_forever())
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
