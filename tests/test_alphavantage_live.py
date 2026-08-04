"""Does Alpha Vantage still behave the way the adapter expects?

Opt-in, like the Yahoo live check, and for the same reason: a unit suite that
depends on a third party's uptime stops meaning "the parser is correct" and
starts meaning "they answered today".

    pytest -m network

Needs `AIDSS_ALPHAVANTAGE_API_KEY`. A free key is issued in under a minute at
https://www.alphavantage.co/support/#api-key. Without one the tests skip
rather than fail, because a missing key says nothing about the code.

**Budget note.** The free tier allows 25 requests a day and this file spends
four of them. It exists to answer one question - has the contract changed? -
so it asks the smallest number of questions that would reveal that.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from aidss.domain.types import Timeframe
from aidss.plugins.adapters.market_alphavantage import AlphaVantageMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

pytestmark = pytest.mark.network

API_KEY = os.environ.get("AIDSS_ALPHAVANTAGE_API_KEY", "").strip()

#: US equity, because Alpha Vantage's coverage there is the documented case.
#: Whether it covers IDX is a separate question, asked separately below.
REFERENCE_SYMBOL = "IBM"
IDX_TICKER = "BBCA"


@pytest.fixture(scope="module")
def adapter() -> AlphaVantageMarketDataProvider:
    """One adapter for the whole module, which is not an optimisation.

    The free tier also caps requests per second, and the adapter paces itself
    against its *own* last request. A fresh instance per test resets that
    counter, so the tests outran the limit and reported a rate-limit refusal as
    if it were a finding. One instance is also how production uses it: a
    collector holds an adapter, it does not build one per call.
    """
    if not API_KEY:
        pytest.skip("AIDSS_ALPHAVANTAGE_API_KEY is not set")
    # Empty suffix: the reference symbol is already a full Alpha Vantage symbol.
    return AlphaVantageMarketDataProvider(API_KEY, symbol_suffix="")


def test_live_fundamentals_still_parse(adapter: AlphaVantageMarketDataProvider) -> None:
    """The claim the whole adapter rests on."""
    points = adapter.get_fundamentals(REFERENCE_SYMBOL)

    assert points, "OVERVIEW returned nothing for a US equity - the contract may have changed"
    by_metric = {p.metric: p.value for p in points}
    # A handful of metrics that have been in the payload for years. Asserting
    # the whole set would fail on every field Alpha Vantage adds.
    for metric in ("pe_ratio", "market_cap", "book_value_per_share"):
        assert metric in by_metric, f"{metric} disappeared from OVERVIEW"
    assert all(p.period_type == "ttm" for p in points)
    assert all(p.period <= datetime.now(UTC).date() for p in points), (
        "a reporting period in the future means LatestQuarter is being misread"
    )


def test_live_analyst_opinions_are_still_excluded(
    adapter: AlphaVantageMarketDataProvider,
) -> None:
    """A regression here would put another firm's recommendation into the
    evidence base, which is the one thing fundamentals must not carry."""
    names = {p.metric for p in adapter.get_fundamentals(REFERENCE_SYMBOL)}
    assert not {n for n in names if "analyst" in n or "target" in n}


def test_live_daily_candles_still_parse(adapter: AlphaVantageMarketDataProvider) -> None:
    end = datetime.now(UTC)
    candles = adapter.get_historical_candles(
        REFERENCE_SYMBOL, Timeframe.D1, end - timedelta(days=30), end
    )

    assert candles, "no candles returned - the series key or symbol mapping may have changed"
    for candle in candles:
        assert candle.high >= max(candle.open, candle.close)
        assert candle.low <= min(candle.open, candle.close)
        assert candle.volume >= 0
    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps), "the contract is ascending; the API sends descending"


def test_live_idx_coverage_is_reported_honestly(adapter: AlphaVantageMarketDataProvider) -> None:
    """Does Alpha Vantage actually cover IDX fundamentals?

    This is the open question the adapter cannot answer on its own, and the
    answer decides whether the composite configuration in the README is real
    or aspirational. Either outcome passes - an empty result is a legitimate
    "no coverage", which the collector reports as `unsupported` rather than as
    a failure. What must not happen is a crash or a malformed point.
    """
    if not API_KEY:
        pytest.skip("AIDSS_ALPHAVANTAGE_API_KEY is not set")

    adapter = AlphaVantageMarketDataProvider(API_KEY, symbol_suffix=".JKT")
    try:
        points = adapter.get_fundamentals(IDX_TICKER)
    except ProviderUnavailableError as exc:
        if exc.retryable:
            pytest.skip(f"quota or transient failure: {exc}")
        raise

    if not points:
        pytest.skip(
            f"Alpha Vantage publishes no fundamentals for {IDX_TICKER}.JKT - "
            "coverage outside US equities is uneven, and the collector reports "
            "this as unsupported rather than as a failure"
        )

    assert all(p.value is not None for p in points)
    assert all(p.period_type == "ttm" for p in points)
