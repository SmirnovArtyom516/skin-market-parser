import logging
import aiohttp
from datetime import datetime, timezone
from sources.base import BaseNewsSource, NewsArticle, classify_event, classify_sentiment

log = logging.getLogger(__name__)

_SUBREDDITS = ["GlobalOffensive", "cs2"]
_API_URL = "https://www.reddit.com/r/{sub}/hot.json"
_HEADERS = {
    # Reddit требует осмысленный User-Agent, иначе 429/403
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) cs2-market-parser/1.0",
}
_MIN_SCORE = 20  # Снижаем порог: r/cs2 моложе и посты набирают меньше


class RedditSource(BaseNewsSource):
    SOURCE_NAME = "reddit"

    async def fetch(self) -> list[NewsArticle]:
        articles = []

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            for subreddit in _SUBREDDITS:
                url = _API_URL.format(sub=subreddit)
                try:
                    fetched = await self._fetch_subreddit(session, url, subreddit)
                    articles.extend(fetched)
                except Exception:
                    log.exception("Reddit fetch failed for r/%s", subreddit)

        return articles

    async def _fetch_subreddit(
        self, session: aiohttp.ClientSession, url: str, subreddit: str
    ) -> list[NewsArticle]:
        async with session.get(
            url,
            params={"limit": 25},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 429:
                log.warning("Reddit rate limit for r/%s", subreddit)
                return []
            if resp.status == 403:
                log.warning("Reddit blocked request for r/%s (status 403)", subreddit)
                return []
            resp.raise_for_status()
            data = await resp.json()

        articles = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})

            if post.get("score", 0) < _MIN_SCORE or post.get("stickied"):
                continue
            if post.get("is_video") or post.get("post_hint") == "image":
                continue

            title = post.get("title", "")
            content = post.get("selftext", "") or post.get("url", "")
            url_post = f"https://reddit.com{post.get('permalink', '')}"
            published_at = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)

            articles.append(NewsArticle(
                source=self.SOURCE_NAME,
                title=title,
                url=url_post,
                content=content[:1000],
                published_at=published_at,
                event_type=classify_event(title, content),
                sentiment=classify_sentiment(title, content),
            ))

        log.debug("r/%s: %d posts passed filter", subreddit, len(articles))
        return articles
