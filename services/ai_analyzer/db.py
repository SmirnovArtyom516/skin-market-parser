import asyncpg
from config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.pg_dsn, min_size=2, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_unprocessed_news(pool: asyncpg.Pool, limit: int = 20) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, title, content, source, event_type, sentiment, published_at
        FROM news_events
        WHERE is_processed = FALSE
        ORDER BY published_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def get_recent_prices(pool: asyncpg.Pool, limit: int = 100) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT s.id AS skin_id, s.market_hash_name,
               ph.price_usd, ph.volume_24h,
               ph.recorded_at
        FROM price_history ph
        JOIN skins s ON s.id = ph.skin_id
        WHERE ph.source = 'skinport'
          AND ph.recorded_at > NOW() - INTERVAL '3 hours'
          AND ph.volume_24h > 3
        ORDER BY ph.volume_24h DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def save_recommendation(pool: asyncpg.Pool, rec: dict) -> None:
    await pool.execute(
        """
        INSERT INTO recommendations
            (skin_id, action, confidence, current_price, target_price,
             potential_roi, reasoning, news_ids, time_horizon)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::uuid[], $9)
        """,
        rec["skin_id"],
        rec["action"],
        rec["confidence"],
        rec["current_price"],
        rec.get("target_price"),
        rec.get("potential_roi"),
        rec["reasoning"],
        rec.get("news_ids", []),
        rec["time_horizon"],
    )


async def mark_news_processed(pool: asyncpg.Pool, news_ids: list[str]) -> None:
    if not news_ids:
        return
    await pool.execute(
        "UPDATE news_events SET is_processed = TRUE WHERE id = ANY($1::uuid[])",
        news_ids,
    )
