import asyncio
import logging
import aiohttp
from sources.base import BaseSource, PriceRecord

log = logging.getLogger(__name__)

_API_URL = "https://api.dmarket.com/exchange/v1/market/items"
_PAGE_SIZE = 100

# Ценовые диапазоны в центах: (from, to, pages)
_PRICE_RANGES = [
    (100,    500,   3),   # $1–5
    (500,    2000,  4),   # $5–20
    (2000,   10000, 4),   # $20–100
    (10000,  50000, 3),   # $100–500
    (50000,  None,  2),   # $500+
]


class DMarketSource(BaseSource):
    SOURCE_NAME = "dmarket"

    async def fetch(self) -> list[PriceRecord]:
        all_records: dict[str, PriceRecord] = {}

        async with aiohttp.ClientSession() as session:
            for price_from, price_to, max_pages in _PRICE_RANGES:
                label = f"${price_from // 100}–${price_to // 100 if price_to else '∞'}"
                try:
                    records = await self._fetch_range(session, price_from, price_to, max_pages)
                    log.info("DMarket range %s: got %d items", label, len(records))
                    for rec in records:
                        existing = all_records.get(rec.market_hash_name)
                        if existing is None or rec.price_usd < existing.price_usd:
                            all_records[rec.market_hash_name] = rec
                except Exception:
                    log.exception("DMarket range %s failed", label)

                # Пауза между диапазонами чтобы не получить rate limit
                await asyncio.sleep(1)

        return list(all_records.values())

    async def _fetch_range(
        self,
        session: aiohttp.ClientSession,
        price_from: int,
        price_to: int | None,
        max_pages: int,
    ) -> list[PriceRecord]:
        records = []
        cursor = None

        for page in range(max_pages):
            params = {
                "gameId": "a8db",
                "currency": "USD",
                "limit": _PAGE_SIZE,
                "orderBy": "price",
                "orderDir": "asc",
                "priceFrom": price_from,
            }
            if price_to is not None:
                params["priceTo"] = price_to
            if cursor:
                params["cursor"] = cursor

            async with session.get(
                _API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    log.warning("DMarket rate limit hit, sleeping 5s...")
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                data = await resp.json()

            objects = data.get("objects") or []
            if not objects:
                break

            for item in objects:
                price_str = item.get("price", {}).get("USD")
                if not price_str:
                    continue
                price_usd = float(price_str) / 100
                if price_usd <= 0:
                    continue
                title = item.get("title", "")
                records.append(PriceRecord(
                    market_hash_name=title,
                    name=title,
                    price_usd=price_usd,
                    source=self.SOURCE_NAME,
                ))

            cursor = data.get("cursor")
            if not cursor:
                break

            # Небольшая пауза между страницами
            if page < max_pages - 1:
                await asyncio.sleep(0.5)

        return records
