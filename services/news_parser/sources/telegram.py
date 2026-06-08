import logging
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from sources.base import BaseNewsSource, NewsArticle, classify_event, classify_sentiment

log = logging.getLogger(__name__)

# Список каналов для мониторинга (только имя без @)
CHANNELS = [
    "mrtwisternews",
    "cs3news",
]

_BASE_URL = "https://t.me/s/{channel}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class TelegramSource(BaseNewsSource):
    SOURCE_NAME = "telegram"

    async def fetch(self) -> list[NewsArticle]:
        articles = []

        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            for channel in CHANNELS:
                try:
                    posts = await self._fetch_channel(session, channel)
                    log.info("Telegram @%s: fetched %d posts", channel, len(posts))
                    articles.extend(posts)
                except Exception:
                    log.exception("Telegram fetch failed for @%s", channel)

        return articles

    async def _fetch_channel(
        self, session: aiohttp.ClientSession, channel: str
    ) -> list[NewsArticle]:
        url = _BASE_URL.format(channel=channel)

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 404:
                log.warning("Telegram channel @%s not found (404)", channel)
                return []
            resp.raise_for_status()
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        articles = []

        for msg_div in soup.select(".tgme_widget_message"):
            # Текст поста
            text_el = msg_div.select_one(".tgme_widget_message_text")
            if not text_el:
                continue
            text = text_el.get_text(separator=" ", strip=True)
            if not text or len(text) < 20:  # Игнорируем пустые / очень короткие посты
                continue

            # Дата и ссылка на пост
            date_el = msg_div.select_one("a.tgme_widget_message_date")
            post_url = date_el["href"] if date_el and date_el.get("href") else url

            time_el = msg_div.select_one("time[datetime]")
            published_at = datetime.now(tz=timezone.utc)
            if time_el and time_el.get("datetime"):
                try:
                    published_at = datetime.fromisoformat(
                        time_el["datetime"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Первые 80 символов текста используем как заголовок
            title = text[:80].rstrip() + ("…" if len(text) > 80 else "")

            articles.append(NewsArticle(
                source=f"telegram_{channel}",
                title=title,
                url=post_url,
                content=text[:1000],
                published_at=published_at,
                event_type=classify_event(title, text),
                sentiment=classify_sentiment(title, text),
            ))

        return articles
