"""Reddit public search fetcher for stock & market sentiment."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger("aidss.vendors.reddit")

_SEARCH_URL = "https://www.reddit.com/search.json"
_USER_AGENT = "aidss/0.1 (+https://github.com/stock-recommendation)"


def fetch_reddit_posts(
    query: str,
    *,
    limit: int = 15,
    time_filter: str = "month",
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent Reddit posts matching ``query``.

    Returns structured dicts with ``title``, ``subreddit``, ``score``,
    ``num_comments``, ``created_at``, ``selftext``, and ``url``.
    """
    cleaned = query.strip()
    if not cleaned:
        return []

    params = {"q": cleaned, "sort": "relevance", "t": time_filter, "limit": str(limit)}
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}

    try:
        if client is not None:
            resp = client.get(_SEARCH_URL, params=params, headers=headers, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as c:
                resp = c.get(_SEARCH_URL, params=params, headers=headers)
        if resp.status_code != 200:
            logger.debug("Reddit returned %s for %r", resp.status_code, cleaned)
            return []
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Reddit fetch failed for %r: %s", cleaned, exc)
        return []

    children = (payload.get("data") or {}).get("children") or []
    posts: list[dict[str, Any]] = []
    for child in children[:limit]:
        data = child.get("data") or {}
        created_utc = data.get("created_utc")
        created_iso = (
            datetime.fromtimestamp(float(created_utc), tz=UTC).isoformat()
            if created_utc is not None
            else None
        )
        selftext = (data.get("selftext") or "").strip()
        if len(selftext) > 400:
            selftext = selftext[:397] + "..."
        posts.append(
            {
                "source": "reddit",
                "title": (data.get("title") or "").strip(),
                "subreddit": data.get("subreddit", ""),
                "score": data.get("score", 0),
                "num_comments": data.get("num_comments", 0),
                "created_at": created_iso,
                "selftext": selftext,
                "url": data.get("url", ""),
            }
        )
    return posts
