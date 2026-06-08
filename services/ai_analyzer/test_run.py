"""
One-shot test: pulls all DB data, computes price volatility, runs Claude analysis.
Does NOT save to DB or mark news as processed.
"""
import asyncio
import os
import re
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

# force UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import asyncpg
import anthropic
from config import settings

# ── DB queries ────────────────────────────────────────────────────────────────

async def fetch_all_news(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, title, content, source, event_type, sentiment, published_at
        FROM news_events
        ORDER BY published_at DESC
        LIMIT 50
        """
    )
    return [dict(r) for r in rows]


async def fetch_price_volatility(pool: asyncpg.Pool) -> list[dict]:
    """Returns skins with price stats: current, min, max, avg, % swing, volume."""
    rows = await pool.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (skin_id)
                skin_id, price_usd AS current_price, volume_24h, recorded_at
            FROM price_history
            WHERE source = 'skinport'
            ORDER BY skin_id, recorded_at DESC
        ),
        stats AS (
            SELECT
                skin_id,
                MIN(price_usd)                                          AS price_min,
                MAX(price_usd)                                          AS price_max,
                ROUND(AVG(price_usd)::numeric, 2)                      AS price_avg,
                COUNT(*)                                                AS data_points,
                ROUND(
                    (MAX(price_usd) - MIN(price_usd))
                    / NULLIF(MIN(price_usd), 0) * 100
                , 1)                                                    AS swing_pct
            FROM price_history
            WHERE source = 'skinport'
              AND recorded_at > NOW() - INTERVAL '7 days'
            GROUP BY skin_id
        )
        SELECT
            s.market_hash_name,
            s.id AS skin_id,
            l.current_price,
            l.volume_24h,
            st.price_min,
            st.price_max,
            st.price_avg,
            st.swing_pct,
            st.data_points
        FROM latest l
        JOIN skins s ON s.id = l.skin_id
        LEFT JOIN stats st ON st.skin_id = l.skin_id
        WHERE l.volume_24h > 3
        ORDER BY st.swing_pct DESC NULLS LAST, l.volume_24h DESC
        LIMIT 80
        """
    )
    return [dict(r) for r in rows]


# ── Prompt building ────────────────────────────────────────────────────────────

def build_prompt(news: list[dict], prices: list[dict]) -> str:
    news_lines = []
    for item in news:
        sentiment_str = {1: "positive", 0: "neutral", -1: "negative"}.get(
            item.get("sentiment", 0), "neutral"
        )
        ts = item["published_at"].strftime("%Y-%m-%d %H:%M") if item.get("published_at") else "?"
        news_lines.append(
            f"[{ts} | {item['source']} | {item.get('event_type', 'general')} | {sentiment_str}]\n"
            f"Title: {item['title']}\n"
            f"Content: {(item.get('content') or '')[:500]}"
        )

    price_lines = []
    for p in prices[:70]:
        swing = f"swing={p['swing_pct']}%" if p.get("swing_pct") is not None else "swing=?"
        price_lines.append(
            f"  {p['market_hash_name']}: "
            f"${float(p['current_price']):.2f} "
            f"(vol={p['volume_24h']}, {swing}, "
            f"min=${float(p['price_min'] or p['current_price']):.2f}, "
            f"max=${float(p['price_max'] or p['current_price']):.2f})"
        )

    return (
        f"Analyze {len(news)} CS2 news articles and market volatility data for {len(prices)} skins.\n\n"
        "## NEWS (newest first):\n"
        + "\n\n".join(news_lines)
        + "\n\n## PRICE DATA (sorted by 7-day price swing, highest volatility first):\n"
        "Format: name: current_price (volume, swing=max_swing_% over 7 days, min, max)\n"
        + "\n".join(price_lines)
        + "\n\n"
        "Focus on:\n"
        "1. Skins with HIGH volatility (large swing%) that have a news catalyst — best entry/exit signals\n"
        "2. Skins near their 7-day LOW with positive news catalyst — asymmetric buy opportunities\n"
        "3. Skins near their 7-day HIGH with negative catalyst — sell signals\n"
        "Call submit_recommendations with your top picks."
    )


# ── Claude call ───────────────────────────────────────────────────────────────

SYSTEM = """You are an expert CS2 skin market analyst specializing in volatility-driven trades.
IMPORTANT: All text fields in your response (market_summary, reasoning, catalyst, current_vs_range, note) MUST be written in Russian language.


CS2 market dynamics:
- Major tournaments (ESL, BLAST, PGL) → souvenir packages spike; team stickers rise
- New case releases → new skins spike, competing skins dip
- Game patches → buffed weapon skins rise, nerfed weapon skins fall
- Operation announcements → operation items spike heavily
- Player/team transfers → team stickers and capsules react
- Trade ban news → negative liquidity impact

Volatility trading strategy:
- High-swing skins are already moving — news catalyst tells you DIRECTION
- Buy near 7-day low when catalyst is positive
- Sell / avoid near 7-day high when catalyst is negative or neutral
- Volume > 20 means liquid enough to enter/exit quickly
- confidence=80+ very strong, 60-79 medium, 50-59 weak

Only recommend skins that appear EXACTLY in the price data provided."""

TOOLS = [
    {
        "name": "submit_recommendations",
        "description": "Submit volatility-driven investment recommendations for CS2 skins",
        "input_schema": {
            "type": "object",
            "properties": {
                "top_volatile_skins": {
                    "type": "array",
                    "description": "Top 5 most volatile skins with clear catalysts (ranked by opportunity)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "market_hash_name": {"type": "string"},
                            "action": {"type": "string", "enum": ["buy", "watch", "sell"]},
                            "confidence": {"type": "number", "description": "0-100"},
                            "current_vs_range": {
                                "type": "string",
                                "description": "e.g. 'near 7d low ($12.50 vs min $11.80 / max $18.00)'"
                            },
                            "catalyst": {
                                "type": "string",
                                "description": "Which specific news drives this move"
                            },
                            "reasoning": {"type": "string"},
                            "time_horizon": {"type": "string", "enum": ["short", "medium", "long"]},
                            "potential_roi": {"type": "number", "description": "% upside/downside"}
                        },
                        "required": [
                            "market_hash_name", "action", "confidence",
                            "current_vs_range", "catalyst", "reasoning",
                            "time_horizon", "potential_roi"
                        ]
                    }
                },
                "market_summary": {
                    "type": "string",
                    "description": "3-4 sentences: overall market mood, biggest volatility drivers, key risks"
                },
                "volatility_leaders": {
                    "type": "array",
                    "description": "Top 3 most volatile skins by swing% regardless of recommendation",
                    "items": {
                        "type": "object",
                        "properties": {
                            "market_hash_name": {"type": "string"},
                            "swing_pct": {"type": "number"},
                            "note": {"type": "string"}
                        },
                        "required": ["market_hash_name", "swing_pct", "note"]
                    }
                }
            },
            "required": ["top_volatile_skins", "market_summary", "volatility_leaders"]
        }
    }
]


def _fix_leaked_params(result: dict) -> dict:
    """Claude sometimes leaks XML parameter tags into the first text field.
    This extracts any embedded JSON fields and cleans the summary."""
    summary = result.get("market_summary", "")
    if "</parameter>" not in summary:
        return result
    result["market_summary"] = summary.split("</parameter>")[0].strip()
    for match in re.finditer(r'<parameter name="(\w+)">(.*?)(?:</parameter>|$)', summary, re.DOTALL):
        key, raw = match.group(1), match.group(2).strip()
        if key not in result or not result[key]:
            try:
                result[key] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return result


async def run_analysis(news: list[dict], prices: list[dict]) -> tuple[dict | None, datetime]:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    prompt = build_prompt(news, prices)

    print(f"\n>> Отправка в Claude: {len(news)} новостей, {len(prices)} скинов...\n")

    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        system=SYSTEM,
        tools=TOOLS,
        tool_choice={"type": "tool", "name": "submit_recommendations"},
        messages=[{"role": "user", "content": prompt}],
    )

    responded_at = datetime.now()
    print(f"[OK] Claude ответил (входящих токенов: {response.usage.input_tokens}, исходящих: {response.usage.output_tokens})\n")

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_recommendations":
            return _fix_leaked_params(dict(block.input)), responded_at

    return None, responded_at


# ── Output formatting ─────────────────────────────────────────────────────────

def _lookup_price(price_map: dict, name: str) -> dict | None:
    # Claude sometimes omits the ★ prefix for knives/gloves
    return price_map.get(name) or price_map.get(f"★ {name}")


def print_results(result: dict, prices: list[dict]) -> None:
    price_map = {p["market_hash_name"]: p for p in prices}

    print("=" * 70)
    print("  АНАЛИЗ РЫНКА CS2 — ВОЛАТИЛЬНОСТЬ И РЕКОМЕНДАЦИИ К ПОКУПКЕ")
    print("=" * 70)

    print(f"\nОБЗОР РЫНКА:\n{result.get('market_summary', 'Нет данных')}\n")

    leaders = result.get("volatility_leaders", [])
    if leaders:
        print("ТОП ВОЛАТИЛЬНЫХ СКИНОВ (7 дней):")
        for i, v in enumerate(leaders, 1):
            print(f"  {i}. {v['market_hash_name']} — качели {v.get('swing_pct', '?')}%  |  {v.get('note', '')}")
        print()

    recs = result.get("top_volatile_skins", [])
    if not recs:
        print("[!] Рекомендаций не получено.")
        return

    action_labels = {"buy": "ПОКУПАТЬ", "sell": "ПРОДАВАТЬ", "watch": "СЛЕДИТЬ"}
    horizon_labels = {"short": "1-7 дней", "medium": "1-4 недели", "long": "1-3 месяца"}

    print(f"РЕКОМЕНДАЦИИ ({len(recs)} позиций):\n")
    for i, rec in enumerate(recs, 1):
        name = rec["market_hash_name"]
        p = _lookup_price(price_map, name)
        action = action_labels.get(rec["action"], rec["action"].upper())
        confidence = rec.get("confidence", 0)
        roi = rec.get("potential_roi", 0)
        horizon = horizon_labels.get(rec.get("time_horizon", ""), rec.get("time_horizon", ""))

        current = float(p["current_price"]) if p else 0.0
        target = round(current * (1 + roi / 100), 2) if current and roi else "?"

        print(f"  {'─'*64}")
        print(f"  #{i}  {action}  |  уверенность: {confidence:.0f}%  |  ROI: {roi:+.1f}%  |  {horizon}")
        print(f"       {name}")
        print(f"       Цена: ${current:.2f}  ->  цель ~${target}")
        print(f"       Диапазон: {rec.get('current_vs_range', '')}")
        print(f"       Катализатор: {rec.get('catalyst', '')}")
        print(f"       Обоснование: {rec.get('reasoning', '')}")
        print()

    print("=" * 70)
    print("  В базу данных ничего не записано.")
    print("=" * 70)


def save_result(result: dict, responded_at) -> str:
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    filename = responded_at.strftime("analysis_%Y-%m-%d_%H-%M-%S.json")
    filepath = os.path.join(results_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return filepath


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    if not settings.anthropic_api_key or settings.anthropic_api_key == "your_key_here":
        print("ОШИБКА: ANTHROPIC_API_KEY не задан в .env")
        sys.exit(1)

    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=1, max_size=3)
    print("[OK] PostgreSQL подключён")

    print("Загрузка данных из БД...")
    news = await fetch_all_news(pool)
    prices = await fetch_price_volatility(pool)

    print(f"   Новостей: {len(news)}")
    print(f"   Скинов с ценами: {len(prices)}")

    if not news:
        print("[!] Новостей в БД нет. Сначала запустите парсер новостей.")
        await pool.close()
        return

    if not prices:
        print("[!] Данных о ценах нет. Сначала запустите парсер цен.")
        await pool.close()
        return

    result, responded_at = await run_analysis(news, prices)

    if result:
        print_results(result, prices)
        filepath = save_result(result, responded_at)
        print(f"\nJSON сохранён: {filepath}")
    else:
        print("[!] Claude не вернул результат")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
