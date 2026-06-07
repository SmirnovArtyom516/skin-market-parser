import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import cache
import db
from sources import ALL_SOURCES

log = logging.getLogger(__name__)


async def collect_prices(pool: asyncpg.Pool) -> None:
    """Собирает цены со всех источников и сохраняет в БД + Redis."""
    for source_cls in ALL_SOURCES:
        source = source_cls()
        log.info("Fetching prices from %s...", source.SOURCE_NAME)

        try:
            records = await source.fetch()
        except Exception:
            log.exception("Failed to fetch from %s", source.SOURCE_NAME)
            continue

        if not records:
            log.warning("No records from %s", source.SOURCE_NAME)
            continue

        # Upsert скинов и собираем их UUID
        price_rows = []
        for rec in records:
            try:
                skin_id = await db.upsert_skin(pool, rec.market_hash_name, rec.name)
                price_rows.append({
                    "skin_id": skin_id,
                    "source": source.SOURCE_NAME,
                    "price_usd": rec.price_usd,
                    "volume_24h": rec.volume_24h,
                })
            except Exception:
                log.exception("Failed to upsert skin %s", rec.market_hash_name)

        # Сохраняем в БД
        await db.save_prices(pool, price_rows)

        # Кешируем в Redis (30 минут)
        await cache.cache_prices(source.SOURCE_NAME, price_rows)
        await cache.set_last_run(source.SOURCE_NAME)

        log.info(
            "[%s] Saved %d prices at %s",
            source.SOURCE_NAME,
            len(price_rows),
            datetime.now(timezone.utc).isoformat(),
        )


def create_scheduler(pool: asyncpg.Pool) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        collect_prices,
        trigger="interval",
        minutes=30,
        args=[pool],
        id="collect_prices",
        next_run_time=datetime.now(timezone.utc),  # запустить сразу при старте
    )
    return scheduler
