from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PriceRecord:
    market_hash_name: str
    name: str
    price_usd: float
    volume_24h: int | None = None
    source: str = ""


class BaseSource(ABC):
    SOURCE_NAME: str = ""

    @abstractmethod
    async def fetch(self) -> list[PriceRecord]:
        """Получить актуальные цены с площадки."""
        ...
