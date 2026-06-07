import aiohttp
from datetime import datetime, timezone
from sources.base import BaseNewsSource, NewsArticle, classify_event, classify_sentiment
from bs4 import BeautifulSoup

# Официальный Steam News API — не требует авторизации
_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"


class SteamNewsSource(BaseNewsSource):
    SOURCE_NAME = "steam"

    async def fetch(self) -> list[NewsArticle]:
        params = {
            "appid": 730,         # CS2
            "count": 20,
            "maxlength": 2000,
            "format": "json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                _API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        items = data.get("appnews", {}).get("newsitems", [])
        articles = []

        for item in items:
            raw_content = item.get("contents", "") or ""
            # Steam возвращает HTML — очищаем теги (только если есть реальная разметка)
            if "<" in raw_content:
                content = BeautifulSoup(raw_content, "html.parser").get_text(separator=" ").strip()
            else:
                content = raw_content.strip()
            title = item.get("title", "")
            url = item.get("url", "")
            published_at = datetime.fromtimestamp(item.get("date", 0), tz=timezone.utc)

            articles.append(NewsArticle(
                source=self.SOURCE_NAME,
                title=title,
                url=url,
                content=content[:1000],
                published_at=published_at,
                event_type=classify_event(title, content),
                sentiment=classify_sentiment(title, content),
            ))

        return articles
