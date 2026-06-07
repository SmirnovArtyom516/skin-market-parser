import asyncio
import logging
import signal
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import db
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Starting News Parser Service...")

    pool = await db.get_pool()
    log.info("PostgreSQL connected.")

    scheduler = create_scheduler(pool)
    scheduler.start()
    log.info("Scheduler started. Collecting news every 15 minutes.")

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
    log.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
