"""StockTwits public symbol-stream fetcher."""

from __future__ import annotations

import html
import logging
from typing import Any

import httpx

logger = logging.getLogger("aidss.vendors.stocktwits")

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_USER_AGENT = "aidss/0.1 (+https://github.com/stock-recommendation)"


def _normalize_symbol(ticker: str) -> str:
    """Normalize ticker for StockTwits (strips .JK suffix for US-like lookup)."""
    cleaned = ticker.strip().upper()
    if cleaned.endswith("-USD"):
        return f"{cleaned[:-4]}.X"
    return cleaned


def fetch_stocktwits_messages(
    ticker: str,
    *,
    limit: int = 30,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent StockTwits messages for ``ticker``.

    Returns a list of structured dicts (``body``, ``sentiment``, ``created_at``,
    ``user``). Returns an empty list on HTTP errors or unsupported symbols.
    """
    symbol = _normalize_symbol(ticker)
    if not symbol:
        return []

    url = _API.format(ticker=symbol)
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    try:
        if client is not None:
            resp = client.get(url, headers=headers, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as c:
                resp = c.get(url, headers=headers)
        if resp.status_code != 200:
            logger.debug("StockTwits returned %s for %s", resp.status_code, symbol)
            return []
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("StockTwits fetch failed for %s: %s", symbol, exc)
        return []

    messages = payload.get("messages") or []
    results: list[dict[str, Any]] = []
    for msg in messages[:limit]:
        entities = msg.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic")
        user_obj = msg.get("user") or {}
        results.append(
            {
                "source": "stocktwits",
                "body": html.unescape(msg.get("body") or "").strip(),
                "sentiment": sentiment,
                "created_at": msg.get("created_at"),
                "user": user_obj.get("username", ""),
            }
        )
    return results
