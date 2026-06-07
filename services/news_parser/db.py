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


async def save_article(pool: asyncpg.Pool, article) -> bool:
    """
    Сохраняет статью. Возвращает True если статья новая, False если дубликат.
    Дедупликация по URL — один и тот же материал не запишется дважды.
    """
    result = await pool.fetchrow(
        """
        INSERT INTO news_events (source, source_url, title, content, event_type, sentiment, published_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (source_url) DO NOTHING
        RETURNING id
        """,
        article.source,
        article.url,
        article.title,
        article.content,
        article.event_type,
        article.sentiment,
        article.published_at,
    )
    return result is not None
