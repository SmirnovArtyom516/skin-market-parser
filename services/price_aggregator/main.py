import asyncio
import logging
import signal
import sys
import os

# Добавляем корень сервиса в path чтобы работали относительные импорты
sys.path.insert(0, os.path.dirname(__file__))

import cache
import db
from scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Starting Price Aggregator Service...")

    pool = await db.get_pool()
    log.info("PostgreSQL connected.")

    scheduler = create_scheduler(pool)
    scheduler.start()
    log.info("Scheduler started. Next run: every 30 minutes.")

    stop_event = asyncio.Event()

    def _shutdown(*_):
        log.info("Shutting down...")
        stop_event.set()

    # Корректное завершение по Ctrl+C или SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except (NotImplementedError, RuntimeError):
            # Windows не поддерживает add_signal_handler для всех сигналов
            signal.signal(sig, _shutdown)

    await stop_event.wait()

    scheduler.shutdown(wait=False)
    await db.close_pool()
    await cache.close()
    log.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
