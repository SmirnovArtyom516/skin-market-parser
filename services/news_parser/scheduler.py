import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
from sources import ALL_SOURCES

log = logging.getLogger(__name__)


async def collect_news(pool: asyncpg.Pool) -> None:
    total_new = 0

    for source_cls in ALL_SOURCES:
        source = source_cls()
        log.info("Fetching news from %s...", source.SOURCE_NAME)

        try:
            articles = await source.fetch()
        except Exception:
            log.exception("Failed to fetch from %s", source.SOURCE_NAME)
            continue

        new_count = 0
        for article in articles:
            try:
                is_new = await db.save_article(pool, article)
                if is_new:
                    new_count += 1
            except Exception:
                log.exception("Failed to save article: %s", article.title[:60])

        log.info("[%s] %d new / %d total at %s",
                 source.SOURCE_NAME, new_count, len(articles),
                 datetime.now(timezone.utc).strftime("%H:%M:%S"))
        total_new += new_count

        await asyncio.sleep(1)

    log.info("News collection done. %d new articles total.", total_new)


def create_scheduler(pool: asyncpg.Pool) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        collect_news,
        trigger="interval",
        minutes=15,         # новости собираем чаще чем цены
        args=[pool],
        id="collect_news",
        next_run_time=datetime.now(timezone.utc),
    )
    return scheduler
