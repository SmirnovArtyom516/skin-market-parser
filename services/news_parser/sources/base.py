from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsArticle:
    source: str
    title: str
    url: str
    content: str
    published_at: datetime
    event_type: str = "general"   # patch, major, case_drop, trade_ban, team_news, general
    sentiment: int = 0            # -1, 0, 1


# Ключевые слова для автоматической классификации типа события
_EVENT_KEYWORDS: dict[str, list[str]] = {
    "patch": ["patch", "update", "hotfix", "fixed", "bug", "changes to", "improved", "operation"],
    "case_drop": ["case", "capsule", "container", "souvenir", "collection", "sticker"],
    "major": ["major", "tournament", "championship", "blast", "esl", "pgl", "faceit", "playoffs", "qualifier"],
    "trade_ban": ["ban", "suspended", "convicted", "trade hold", "vac"],
    "team_news": ["signed", "roster", "leaves", "joins", "transferred", "announced", "lineup"],
}


def classify_event(title: str, content: str) -> str:
    text = (title + " " + content).lower()
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return event_type
    return "general"


def classify_sentiment(title: str, content: str) -> int:
    text = (title + " " + content).lower()
    positive = ["win", "victory", "new", "release", "launch", "buff", "added", "improved", "rare", "exclusive"]
    negative = ["ban", "suspended", "removed", "loss", "defeat", "nerf", "exploit", "bug", "broken", "crash"]
    pos = sum(1 for w in positive if w in text)
    neg = sum(1 for w in negative if w in text)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


class BaseNewsSource(ABC):
    SOURCE_NAME: str = ""

    @abstractmethod
    async def fetch(self) -> list[NewsArticle]:
        ...
