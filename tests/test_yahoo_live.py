"""Opt-in check against the real Yahoo endpoint.

Deselected by default (`-m "not network"`), because a unit suite that depends
on a third party's uptime fails for reasons that have nothing to do with the
code under test.

Run it deliberately when you want to know whether the unofficial endpoint
still behaves as this adapter expects - which is exactly the risk of depending
on an undocumented source:

    pytest -m network -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss.domain.types import Timeframe
from aidss.plugins.adapters.market_yahoo import YahooMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

pytestmark = pytest.mark.network


@pytest.fixture
def adapter() -> YahooMarketDataProvider:
    return YahooMarketDataProvider()


def test_live_daily_candles_for_an_idx_ticker(adapter: YahooMarketDataProvider) -> None:
    end = datetime.now(UTC)
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, end - timedelta(days=60), end)

    assert candles, "no candles returned - the endpoint or symbol mapping may have changed"
    for candle in candles:
        assert candle.high >= max(candle.open, candle.close)
        assert candle.low <= min(candle.open, candle.close)
        assert candle.volume >= 0
    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps)


def test_live_quote_for_an_idx_ticker(adapter: YahooMarketDataProvider) -> None:
    quote = adapter.get_quote("BBCA")
    assert quote.price > 0
    assert quote.ticker == "BBCA"


def test_live_health_check(adapter: YahooMarketDataProvider) -> None:
    assert adapter.health_check() is True


def test_live_fundamentals_for_an_idx_ticker(adapter: YahooMarketDataProvider) -> None:
    """Whether quoteSummary still returns what the parser expects.

    As of the last run it does not: the endpoint answers 401. Yahoo added
    authentication to it, unlike the chart endpoint the price tests use.

    That is skipped rather than failed, and the distinction is deliberate. The
    test's question is "does the live shape still match the parser?", and
    "the endpoint now requires credentials" is a legitimate answer to that
    question rather than a defect in this code. Any *other* failure still fails,
    so a genuine parser regression is not hidden behind a blanket skip.

    Working around the 401 is out of scope on purpose. Using an undocumented
    but open endpoint is one thing; defeating an access control the provider
    deliberately added is another.
    """
    try:
        points = adapter.get_fundamentals("BBCA")
    except ProviderUnavailableError as exc:
        if "access refused" in str(exc):
            pytest.skip(
                f"Yahoo's quoteSummary endpoint now requires authentication ({exc}). "
                "The parser is exercised against a recorded payload in "
                "test_market_yahoo_fundamentals.py; fundamentals need a provider "
                "that permits programmatic access."
            )
        raise

    for point in points:
        assert point.metric
        assert point.period_type in {"quarterly", "annual", "ttm"}
        assert point.value is None or isinstance(point.value, Decimal)

    metrics = {p.metric for p in points}
    assert len(metrics) == len(points), "a metric was returned twice"
