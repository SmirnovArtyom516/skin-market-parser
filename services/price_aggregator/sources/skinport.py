import aiohttp
from sources.base import BaseSource, PriceRecord

# Skinport публичный API — не требует авторизации
# Docs: https://docs.skinport.com/#get-v1-items
_API_URL = "https://api.skinport.com/v1/items"


class SkinportSource(BaseSource):
    SOURCE_NAME = "skinport"

    async def fetch(self) -> list[PriceRecord]:
        params = {
            "app_id": 730,      # CS2
            "currency": "USD",
        }
        headers = {
            # Skinport требует Accept-Encoding для сжатых ответов
            "Accept-Encoding": "br",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(_API_URL, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)

        records = []
        for item in data:
            min_price = item.get("min_price")
            if min_price is None:
                continue

            records.append(PriceRecord(
                market_hash_name=item["market_hash_name"],
                name=item["market_hash_name"],
                price_usd=min_price / 100,  # Skinport возвращает цену в центах
                volume_24h=item.get("quantity"),
                source=self.SOURCE_NAME,
            ))

        return records
