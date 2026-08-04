"""The composite provider, and the vocabulary two providers have to share.

Two separate concerns live here because they are the same risk seen twice.

The composite exists so prices can come from one source and fundamentals from
another - Yahoo serves IDX prices and 401s on fundamentals, Alpha Vantage
serves fundamentals and caps at 25 requests a day. The tests check that the
delegation is total and that provenance survives it: a metric collected
through a composite must be attributed to whichever half answered, because
`composite` names a wrapper and answers nobody's question about where a figure
came from.

The vocabulary tests check the other half of the same thing. Two adapters can
both be correct in isolation and still be useless together if one writes
`pe_ratio` and the other writes `trailing_pe` - the rows would sit in the same
table, look comparable, and not be.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.adapters.market_alphavantage import (
    _METRIC_NAMES as ALPHAVANTAGE_METRICS,
)
from aidss.plugins.adapters.market_composite import CompositeMarketDataProvider
from aidss.plugins.adapters.market_yahoo import _METRIC_NAMES as YAHOO_METRICS
from aidss.plugins.errors import PluginRegistrationError, ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider

# --- doubles ---------------------------------------------------------------


class RecordingProvider(MarketDataProvider):
    """Records what it was asked, so delegation can be observed rather than assumed."""

    name: ClassVar[str] = "recorder"

    def __init__(self, label: str, *, healthy: bool = True, realtime: bool = False) -> None:
        self.name = label  # type: ignore[misc]
        self.calls: list[str] = []
        self._healthy = healthy
        self._realtime = realtime

    def get_quote(self, ticker: str) -> Quote:
        self.calls.append("get_quote")
        return Quote(ticker=ticker, price=Decimal("1"), timestamp=datetime.now(UTC))

    def get_historical_candles(
        self, ticker: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        self.calls.append("get_historical_candles")
        return [
            Candle(
                timestamp=start,
                open=Decimal("1"),
                high=Decimal("2"),
                low=Decimal("1"),
                close=Decimal("2"),
                volume=Decimal("10"),
            )
        ]

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        self.calls.append("get_fundamentals")
        return [
            FundamentalPoint(
                metric="pe_ratio",
                period=datetime.now(UTC).date(),
                value=Decimal("12.5"),
                period_type="ttm",
            )
        ]

    def supports_realtime(self) -> bool:
        return self._realtime

    def health_check(self) -> bool:
        self.calls.append("health_check")
        return self._healthy


@pytest.fixture
def halves() -> tuple[RecordingProvider, RecordingProvider]:
    return RecordingProvider("prices"), RecordingProvider("fundamentals")


@pytest.fixture
def composite(halves) -> CompositeMarketDataProvider:
    prices, fundamentals = halves
    return CompositeMarketDataProvider(prices=prices, fundamentals=fundamentals)


# --- delegation ------------------------------------------------------------


def test_prices_go_to_the_price_half_only(composite, halves) -> None:
    prices, fundamentals = halves
    composite.get_quote("BBCA")
    composite.get_historical_candles(
        "BBCA", Timeframe.D1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    )

    assert prices.calls == ["get_quote", "get_historical_candles"]
    assert fundamentals.calls == []


def test_fundamentals_go_to_the_fundamentals_half_only(composite, halves) -> None:
    prices, fundamentals = halves
    points = composite.get_fundamentals("BBCA")

    assert fundamentals.calls == ["get_fundamentals"]
    assert prices.calls == []
    assert [p.metric for p in points] == ["pe_ratio"]


def test_arguments_are_passed_through_untouched(composite, halves) -> None:
    """The composite must add no normalisation of its own, or it would
    develop opinions that differ from the adapter behind it."""
    start = datetime(2026, 3, 1, tzinfo=UTC)
    candles = composite.get_historical_candles("BBCA", Timeframe.D1, start, start)
    assert candles[0].timestamp == start


def test_realtime_is_answered_by_the_price_half() -> None:
    composite = CompositeMarketDataProvider(
        prices=RecordingProvider("p", realtime=True),
        fundamentals=RecordingProvider("f", realtime=False),
    )
    assert composite.supports_realtime() is True


def test_an_error_from_a_half_is_not_swallowed(composite, halves) -> None:
    """A composite that degraded quietly would hide the outage it exists to expose."""
    prices, _ = halves

    def fail(ticker: str) -> Quote:
        raise ProviderUnavailableError("prices", "down", retryable=True)

    prices.get_quote = fail  # type: ignore[method-assign]
    with pytest.raises(ProviderUnavailableError):
        composite.get_quote("BBCA")


# --- provenance ------------------------------------------------------------


def test_a_fundamental_figure_is_attributed_to_the_half_that_answered(composite) -> None:
    """`composite` would name a wrapper, not a source."""
    assert composite.fundamentals_source_name() == "fundamentals"


def test_describe_reports_both_halves(composite) -> None:
    assert composite.describe() == {"prices": "prices", "fundamentals": "fundamentals"}


def test_a_plain_adapter_attributes_to_itself() -> None:
    """The interface default, so no adapter has to opt in."""
    assert RecordingProvider("yahoo").fundamentals_source_name() == "yahoo"


def test_the_collector_records_the_concrete_source(session) -> None:
    """End to end, through the collector that actually writes the row."""
    from sqlalchemy import select

    from aidss.collectors.market_data import FundamentalCollector
    from aidss.db.models import Asset, FundamentalMetric

    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add(asset)
    session.flush()

    composite = CompositeMarketDataProvider(
        prices=RecordingProvider("yahoo"),
        fundamentals=RecordingProvider("alphavantage"),
    )
    FundamentalCollector(composite).collect(session, asset)

    stored = session.scalars(select(FundamentalMetric)).all()
    assert stored
    assert {row.source for row in stored} == {"alphavantage"}


# --- health ----------------------------------------------------------------


def test_health_requires_both_halves() -> None:
    """Reporting healthy while fundamentals are down would hide exactly the
    failure this adapter was built to make visible."""
    composite = CompositeMarketDataProvider(
        prices=RecordingProvider("p", healthy=True),
        fundamentals=RecordingProvider("f", healthy=False),
    )
    assert composite.health_check() is False


def test_health_passes_when_both_are_up() -> None:
    composite = CompositeMarketDataProvider(
        prices=RecordingProvider("p"), fundamentals=RecordingProvider("f")
    )
    assert composite.health_check() is True


# --- construction guards ---------------------------------------------------


def test_a_composite_cannot_wrap_a_composite(composite) -> None:
    """Otherwise it recurses until the stack ends, and the traceback names
    this file a hundred times without saying why."""
    with pytest.raises(ValueError, match="cannot delegate to another composite"):
        CompositeMarketDataProvider(prices=composite, fundamentals=RecordingProvider("f"))


def test_configuration_pointing_a_half_at_composite_is_refused() -> None:
    settings = Settings(
        composite_price_provider="composite",
        composite_fundamentals_provider="fixture",
        jwt_secret="x" * 32,
    )
    with pytest.raises(PluginRegistrationError, match="cannot be 'composite'"):
        CompositeMarketDataProvider.from_settings(settings)


def test_an_unregistered_half_names_what_is_available() -> None:
    from aidss.plugins.errors import PluginNotFoundError

    settings = Settings(
        composite_price_provider="nonexistent",
        composite_fundamentals_provider="fixture",
        jwt_secret="x" * 32,
    )
    with pytest.raises(PluginNotFoundError, match="Available:"):
        CompositeMarketDataProvider.from_settings(settings)


def test_the_composite_is_resolvable_from_configuration_alone() -> None:
    """FR-07: choosing it is a settings change, not a code change."""
    from aidss.plugins.registry import get_market_data_provider

    settings = Settings(
        market_data_provider="composite",
        composite_price_provider="fixture",
        composite_fundamentals_provider="fixture",
        jwt_secret="x" * 32,
    )
    provider = get_market_data_provider(settings)
    assert isinstance(provider, CompositeMarketDataProvider)
    assert provider.describe() == {"prices": "fixture", "fundamentals": "fixture"}


# --- the shared metric vocabulary ------------------------------------------


#: Metrics both providers publish. If one adapter renames its side, the rows
#: stop being comparable while still looking like they are - so the overlap is
#: pinned rather than left to drift.
SHARED = {
    "pe_ratio",
    "forward_pe_ratio",
    "price_to_book",
    "ev_to_ebitda",
    "ev_to_revenue",
    "return_on_equity",
    "return_on_assets",
    "profit_margin",
    "operating_margin",
    "total_revenue",
    "revenue_growth",
    "earnings_growth",
    "dividend_yield",
    "book_value_per_share",
    "eps_trailing",
    "beta",
    "market_cap",
    "ebitda",
}


def test_both_providers_use_the_same_names_for_the_same_metrics() -> None:
    yahoo = set(YAHOO_METRICS.values())
    alphavantage = set(ALPHAVANTAGE_METRICS.values())

    missing_from_yahoo = SHARED - yahoo
    missing_from_alphavantage = SHARED - alphavantage
    assert not missing_from_yahoo, f"Yahoo no longer publishes {sorted(missing_from_yahoo)}"
    assert not missing_from_alphavantage, (
        f"Alpha Vantage no longer publishes {sorted(missing_from_alphavantage)}"
    )


def test_neither_provider_maps_two_fields_onto_one_metric() -> None:
    """A duplicate mapping makes which value wins depend on dict ordering."""
    for label, mapping in (("yahoo", YAHOO_METRICS), ("alphavantage", ALPHAVANTAGE_METRICS)):
        values = list(mapping.values())
        duplicates = {v for v in values if values.count(v) > 1}
        assert not duplicates, f"{label} maps more than one field onto {sorted(duplicates)}"


def test_metric_names_are_lowercase_snake_case() -> None:
    """They are stored as strings and queried by hand; a stray capital in one
    adapter would silently split a metric into two."""
    import re

    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    for mapping in (YAHOO_METRICS, ALPHAVANTAGE_METRICS):
        offenders = [name for name in mapping.values() if not pattern.match(name)]
        assert not offenders, f"not snake_case: {offenders}"
