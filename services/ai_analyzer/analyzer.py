import logging
import anthropic
from config import settings

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


_TOOLS = [
    {
        "name": "submit_recommendations",
        "description": "Submit investment recommendations for CS2 skins based on market analysis",
        "input_schema": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "description": "List of investment recommendations (max 5 strongest signals)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "market_hash_name": {
                                "type": "string",
                                "description": "Exact CS2 skin market hash name (must match the price list)"
                            },
                            "action": {
                                "type": "string",
                                "enum": ["buy", "watch", "sell"],
                                "description": "buy=strong entry signal, watch=monitor closely, sell=exit position"
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence score 0-100 (e.g. 75 = 75% confident)"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Concise reasoning: what news triggered this, why this skin specifically"
                            },
                            "time_horizon": {
                                "type": "string",
                                "enum": ["short", "medium", "long"],
                                "description": "short=1-7 days, medium=1-4 weeks, long=1-3 months"
                            },
                            "potential_roi": {
                                "type": "number",
                                "description": "Expected price change in % (e.g. 20.5 for +20.5%, -10 for -10%)"
                            }
                        },
                        "required": [
                            "market_hash_name", "action", "confidence",
                            "reasoning", "time_horizon", "potential_roi"
                        ]
                    }
                },
                "market_summary": {
                    "type": "string",
                    "description": "2-3 sentence overall market outlook based on current news"
                }
            },
            "required": ["recommendations", "market_summary"]
        }
    }
]

_SYSTEM = """You are an expert CS2 skin market analyst. Your goal is to identify short and medium-term
investment opportunities based on esports news, game updates, and current market data.

Key CS2 skin market dynamics:
- Major tournaments (ESL, BLAST, PGL) → souvenir package prices spike for maps played; team stickers rise
- New case announcements → new skins initially spike, old competing skins dip
- Game patches affecting gameplay → popular weapon skins for buffed weapons can rise
- Operation announcements → operation items, missions, new cases spike heavily
- Trade ban changes (new countries) → reduces liquidity, usually negative overall
- Player/team transfers → team-specific stickers and capsules react
- Large-scale cheating bans → temporary confidence drop, then recovery
- Steam sales / Valve sales → liquidity increases, prices often temporarily drop then recover
- Positive major news → market-wide bullish sentiment lifts all boats

When analyzing:
1. Only recommend skins that appear EXACTLY in the provided price list
2. Focus on skins with volume > 10 (liquid markets)
3. Be selective: 1-3 strong picks beats 10 weak ones
4. confidence=80+ means very strong signal, 60-79 medium, 50-59 weak (don't recommend below 50)
5. For "buy" actions, the news must have a clear positive catalyst for this specific skin category
6. For "sell", prices must be near recent highs with negative catalyst incoming"""


def _build_prompt(news_items: list[dict], prices: list[dict]) -> str:
    news_lines = []
    for item in news_items:
        sentiment_str = {1: "positive", 0: "neutral", -1: "negative"}.get(
            item.get("sentiment", 0), "neutral"
        )
        news_lines.append(
            f"[{item['source']} | {item.get('event_type', 'general')} | {sentiment_str}]\n"
            f"Title: {item['title']}\n"
            f"Content: {(item.get('content') or '')[:400]}"
        )

    price_lines = [
        f"  {p['market_hash_name']}: ${float(p['price_usd']):.2f} (vol={p['volume_24h']})"
        for p in prices[:60]
    ]

    return (
        f"Analyze the following {len(news_items)} recent CS2 news articles "
        f"and current market prices, then call submit_recommendations.\n\n"
        f"## NEWS:\n"
        + "\n\n".join(news_lines)
        + f"\n\n## CURRENT PRICES (top {len(price_lines)} skins by volume):\n"
        + "\n".join(price_lines)
        + "\n\nBased on the news, identify investment opportunities. "
        "Only include skins from the price list above with clear catalysts."
    )


async def analyze(news_items: list[dict], prices: list[dict]) -> dict | None:
    if not news_items or not prices:
        return None

    client = _get_client()
    prompt = _build_prompt(news_items, prices)

    log.info("Calling Claude with %d news and %d prices", len(news_items), len(prices))

    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        system=_SYSTEM,
        tools=_TOOLS,
        tool_choice={"type": "tool", "name": "submit_recommendations"},
        messages=[{"role": "user", "content": prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_recommendations":
            recs = block.input.get("recommendations", [])
            log.info(
                "Claude returned %d recommendations (input_tokens=%d, output_tokens=%d)",
                len(recs),
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            return block.input

    log.warning("Claude did not return recommendations")
    return None
