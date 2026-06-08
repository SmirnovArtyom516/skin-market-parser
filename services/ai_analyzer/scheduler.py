import logging
from datetime import datetime

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from analyzer import analyze
from db import (
    get_unprocessed_news,
    get_recent_prices,
    mark_news_processed,
    save_recommendation,
)

log = logging.getLogger(__name__)


async def run_analysis(pool: asyncpg.Pool) -> None:
    news = await get_unprocessed_news(pool, limit=20)
    if not news:
        log.info("No unprocessed news — skipping AI analysis")
        return

    prices = await get_recent_prices(pool, limit=100)
    if not prices:
        log.info("No recent price data — skipping AI analysis")
        return

    log.info("Starting analysis: %d news articles, %d skins", len(news), len(prices))

    result = await analyze(news, prices)
    if not result:
        log.warning("AI analysis returned no result")
        return

    price_map = {p["market_hash_name"]: p for p in prices}
    news_ids = [str(n["id"]) for n in news]

    saved = 0
    for rec in result.get("recommendations", []):
        market_name = rec.get("market_hash_name", "")
        price_info = price_map.get(market_name)

        if not price_info:
            log.warning("Skin not in price data, skipping: %s", market_name)
            continue

        confidence = float(rec.get("confidence", 0))
        if confidence < 50:
            log.debug("Skipping low-confidence rec (%.0f%%): %s", confidence, market_name)
            continue

        current_price = float(price_info["price_usd"])
        roi = rec.get("potential_roi")

        target_price = None
        if roi is not None and current_price > 0:
            target_price = round(current_price * (1 + float(roi) / 100), 2)

        try:
            await save_recommendation(
                pool,
                {
                    "skin_id": str(price_info["skin_id"]),
                    "action": rec["action"],
                    "confidence": confidence,
                    "current_price": current_price,
                    "target_price": target_price,
                    "potential_roi": roi,
                    "reasoning": rec.get("reasoning", ""),
                    "news_ids": news_ids,
                    "time_horizon": rec.get("time_horizon", "medium"),
                },
            )
            saved += 1
            log.info(
                "[%s] %s @ $%.2f → target $%.2f (roi=%.1f%%, conf=%.0f%%)",
                rec["action"].upper(),
                market_name,
                current_price,
                target_price or 0,
                roi or 0,
                confidence,
            )
        except Exception:
            log.exception("Failed to save recommendation for %s", market_name)

    await mark_news_processed(pool, news_ids)

    summary = result.get("market_summary", "")
    log.info(
        "Analysis complete: %d recommendations saved, %d news marked processed",
        saved,
        len(news_ids),
    )
    if summary:
        log.info("Market summary: %s", summary)


def create_scheduler(pool: asyncpg.Pool) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    async def _job():
        try:
            await run_analysis(pool)
        except Exception:
            log.exception("AI analysis job failed")

    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(minutes=30),
        id="ai_analysis",
        name="AI Analysis",
        next_run_time=datetime.now(),
    )

    return scheduler
