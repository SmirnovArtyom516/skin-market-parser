import asyncpg
from config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.pg_dsn, min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def upsert_skin(pool: asyncpg.Pool, market_hash_name: str, name: str) -> str:
    """Вставляет скин если не существует, возвращает его UUID."""
    row = await pool.fetchrow(
        """
        INSERT INTO skins (market_hash_name, name)
        VALUES ($1, $2)
        ON CONFLICT (market_hash_name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        market_hash_name,
        name,
    )
    return str(row["id"])


async def save_prices(pool: asyncpg.Pool, records: list[dict]) -> None:
    """
    records: list of {skin_id, source, price_usd, volume_24h}
    Пишем батчем через copy для скорости.
    """
    await pool.executemany(
        """
        INSERT INTO price_history (skin_id, source, price_usd, volume_24h)
        VALUES ($1::uuid, $2, $3, $4)
        """,
        [
            (r["skin_id"], r["source"], r["price_usd"], r.get("volume_24h"))
            for r in records
        ],
    )


async def get_skin_ids(pool: asyncpg.Pool) -> dict[str, str]:
    """Возвращает {market_hash_name: uuid} для всех скинов в БД."""
    rows = await pool.fetch("SELECT id, market_hash_name FROM skins")
    return {row["market_hash_name"]: str(row["id"]) for row in rows}
