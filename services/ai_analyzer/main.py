import asyncio
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(__file__))

import db
from config import settings
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


async def main() -> None:
    if not settings.anthropic_api_key or settings.anthropic_api_key == "your_key_here":
        log.error("ANTHROPIC_API_KEY not configured in .env")
        sys.exit(1)

    pool = await db.get_pool()
    log.info("PostgreSQL connected")

    scheduler = create_scheduler(pool)
    scheduler.start()
    log.info("AI Analyzer started (runs every 30 minutes, immediately on start)")

    stop_event = asyncio.Event()

    def _shutdown(*_):
        log.info("Shutting down...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, _shutdown)

    await stop_event.wait()

    scheduler.shutdown(wait=False)
    await db.close_pool()
    log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
