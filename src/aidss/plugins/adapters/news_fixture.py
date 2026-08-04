"""A deterministic NewsProvider for development and CI.

The full scheduled news pipeline is Phase 7 (Section 6.3); this adapter exists
from Phase 1 so the ``NewsProvider`` contract is pinned down and exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from aidss.config import Settings
from aidss.domain.types import NewsArticle
from aidss.plugins.interfaces import NewsProvider
from aidss.plugins.registry import register

#: Spacing of the synthetic article grid.
_GRID = timedelta(hours=6)

#: Cap per request, so a wide window cannot generate thousands of articles.
_MAX_ARTICLES = 50

_TEMPLATES = [
    ("{ticker} quarterly results summary", "{ticker} published its quarterly financials."),
    ("{ticker} announces expansion plan", "{ticker} management outlined its capex plan."),
    ("Analyst commentary on {ticker}", "Several analysts revised their view on {ticker}."),
]


@register
class FixtureNewsProvider(NewsProvider):
    name: ClassVar[str] = "fixture"

    @classmethod
    def from_settings(cls, settings: Settings) -> FixtureNewsProvider:  # noqa: ARG003
        return cls()

    def get_news(self, ticker: str, start: datetime, end: datetime) -> list[NewsArticle]:
        """Articles on a fixed six-hour grid within the requested window.

        Anchored to an absolute grid rather than generated relative to
        ``start``, for the same reason the market fixture is: overlapping
        windows must return the *same* articles. A fixture that invents a fresh
        article at whatever moment it was asked would make deduplication and
        idempotency untestable - and would make them look broken when they are
        not.
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start > end:
            raise ValueError("start must not be after end")

        ticker = ticker.upper()
        step = int(_GRID.total_seconds())
        epoch = datetime(1970, 1, 1, tzinfo=UTC)

        first = -(-int((start - epoch).total_seconds()) // step)
        last = int((end - epoch).total_seconds()) // step

        articles: list[NewsArticle] = []
        for slot in range(first, min(last, first + _MAX_ARTICLES - 1) + 1):
            published = epoch + timedelta(seconds=slot * step)
            headline, summary = _TEMPLATES[slot % len(_TEMPLATES)]
            articles.append(
                NewsArticle(
                    source="fixture-newswire",
                    # The collector deduplicates on a hash of URL and headline
                    # (Section 6.3.3, step 7), so both are stable per slot.
                    source_url=f"https://fixture.invalid/{ticker}/{slot}",
                    headline=f"{headline.format(ticker=ticker)} ({slot})",
                    summary=summary.format(ticker=ticker),
                    published_at=published,
                    tickers=(ticker,),
                )
            )
        return articles
