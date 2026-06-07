import json
import redis.asyncio as aioredis
from config import settings

_client: aioredis.Redis | None = None


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def cache_prices(source: str, items: list[dict], ttl: int = 1800) -> None:
    """Кеширует список цен от источника на ttl секунд (по умолчанию 30 минут)."""
    client = get_client()
    key = f"prices:{source}"
    await client.setex(key, ttl, json.dumps(items))


async def get_cached_prices(source: str) -> list[dict] | None:
    client = get_client()
    data = await client.get(f"prices:{source}")
    return json.loads(data) if data else None


async def set_last_run(source: str) -> None:
    """Сохраняет timestamp последнего успешного сбора."""
    client = get_client()
    from datetime import datetime, timezone
    await client.set(f"last_run:{source}", datetime.now(timezone.utc).isoformat())


async def close() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
