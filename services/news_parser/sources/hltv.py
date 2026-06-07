import feedparser
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from sources.base import BaseNewsSource, NewsArticle, classify_event, classify_sentiment

# HLTV RSS-лента новостей — работает без Cloudflare защиты
_RSS_URL = "https://www.hltv.org/rss/news"


class HltvSource(BaseNewsSource):
    SOURCE_NAME = "hltv"

    async def fetch(self) -> list[NewsArticle]:
        # feedparser синхронный — запускаем в thread pool чтобы не блокировать event loop
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, _RSS_URL)

        articles = []
        for entry in feed.entries:
            title = entry.get("title", "")
            content = entry.get("summary", "")
            url = entry.get("link", "")

            published_at = datetime.now(tz=timezone.utc)
            raw_date = entry.get("published") or entry.get("updated")
            if raw_date:
                try:
                    published_at = parsedate_to_datetime(raw_date)
                except Exception:
                    pass

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
