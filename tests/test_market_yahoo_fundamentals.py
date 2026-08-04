"""Yahoo fundamentals parsing (quoteSummary), against a mocked transport."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from aidss.collectors.market_data import FundamentalCollector, MarketDataCollector
from aidss.config import Settings
from aidss.plugins.adapters.market_yahoo import YahooMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.registry import get_market_data_provider


def summary_payload(**modules) -> dict:
    return {"quoteSummary": {"error": None, "result": [modules]}}


def provider_returning(payload, *, status: int = 200) -> YahooMarketDataProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        return httpx.Response(status, json=payload)

    return YahooMarketDataProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url=YahooMarketDataProvider.BASE_URL
        )
    )


# --- Parsing ---------------------------------------------------------------


def test_raw_values_are_used_and_formatted_ones_ignored() -> None:
    """Parsing "1.23B" back into a number is locale-dependent and gets it wrong."""
    adapter = provider_returning(
        summary_payload(
            defaultKeyStatistics={"trailingPE": {"raw": 18.42, "fmt": "18.42"}},
            financialData={"totalRevenue": {"raw": 1230000000, "fmt": "1.23B"}},
        )
    )
    points = {p.metric: p.value for p in adapter.get_fundamentals("BBCA")}

    assert points["pe_ratio"] == Decimal("18.42")
    assert points["total_revenue"] == Decimal("1230000000")


def test_a_bare_number_is_accepted_too() -> None:
    adapter = provider_returning(summary_payload(financialData={"currentRatio": 1.8}))
    points = {p.metric: p.value for p in adapter.get_fundamentals("BBCA")}
    assert points["current_ratio"] == Decimal("1.8")


def test_unmapped_fields_are_ignored() -> None:
    """A metric whose definition varies between providers is left out."""
    adapter = provider_returning(
        summary_payload(defaultKeyStatistics={"someUndocumentedField": {"raw": 42}})
    )
    assert adapter.get_fundamentals("BBCA") == []


def test_missing_values_are_skipped_not_stored_as_null() -> None:
    adapter = provider_returning(
        summary_payload(
            defaultKeyStatistics={"trailingPE": {"raw": 18.4}, "forwardPE": {"fmt": "N/A"}}
        )
    )
    metrics = {p.metric for p in adapter.get_fundamentals("BBCA")}
    assert metrics == {"pe_ratio"}


def test_metrics_are_stamped_as_trailing_twelve_months() -> None:
    """They are point-in-time statistics, not a filing period.

    Labelling them as quarterly would let a reader line them up against actual
    quarters they do not correspond to.
    """
    adapter = provider_returning(
        summary_payload(defaultKeyStatistics={"trailingPE": {"raw": 18.4}})
    )
    point = adapter.get_fundamentals("BBCA")[0]
    assert point.period_type == "ttm"
    assert point.period == date.today()


def test_a_metric_in_two_modules_is_stored_once() -> None:
    adapter = provider_returning(
        summary_payload(
            defaultKeyStatistics={"beta": {"raw": 1.1}},
            summaryDetail={"beta": {"raw": 9.9}},
        )
    )
    points = adapter.get_fundamentals("BBCA")
    assert len(points) == 1
    # Module order decides precedence.
    assert points[0].value == Decimal("1.1")


def test_an_issuer_without_coverage_returns_nothing_rather_than_failing() -> None:
    adapter = provider_returning({"quoteSummary": {"error": None, "result": []}})
    assert adapter.get_fundamentals("NOSUCH") == []


def test_an_upstream_error_is_surfaced() -> None:
    adapter = provider_returning(
        {"quoteSummary": {"error": {"description": "Quote not found"}, "result": None}}
    )
    with pytest.raises(ProviderUnavailableError, match="Quote not found"):
        adapter.get_fundamentals("NOSUCH")


def test_a_changed_response_shape_reports_itself() -> None:
    adapter = provider_returning({"unexpected": "shape"})
    with pytest.raises(ProviderUnavailableError, match="unexpected quoteSummary shape"):
        adapter.get_fundamentals("BBCA")


def test_rate_limiting_is_retryable_here_too() -> None:
    adapter = provider_returning({}, status=429)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_fundamentals("BBCA")
    assert excinfo.value.retryable


# --- Collector -------------------------------------------------------------


def test_metrics_are_stored(session) -> None:
    adapter = provider_returning(
        summary_payload(
            defaultKeyStatistics={"trailingPE": {"raw": 18.4}, "priceToBook": {"raw": 2.1}}
        )
    )
    asset = MarketDataCollector(adapter).get_or_create_asset(session, "BBCA")
    report = FundamentalCollector(adapter).collect(session, asset)

    assert report.fetched == 2
    assert report.inserted == 2
    assert not report.unsupported


def test_re_running_stores_nothing_new(session) -> None:
    adapter = provider_returning(
        summary_payload(defaultKeyStatistics={"trailingPE": {"raw": 18.4}})
    )
    asset = MarketDataCollector(adapter).get_or_create_asset(session, "BBCA")
    collector = FundamentalCollector(adapter)

    collector.collect(session, asset)
    second = collector.collect(session, asset)

    assert second.inserted == 0
    assert second.updated == 0


def test_a_restated_figure_replaces_the_old_one(session) -> None:
    """Fundamentals get revised; two versions side by side would be worse."""
    asset = MarketDataCollector(
        provider_returning(summary_payload())
    ).get_or_create_asset(session, "BBCA")

    first = provider_returning(summary_payload(defaultKeyStatistics={"trailingPE": {"raw": 18.4}}))
    FundamentalCollector(first).collect(session, asset)

    revised = provider_returning(
        summary_payload(defaultKeyStatistics={"trailingPE": {"raw": 19.1}})
    )
    report = FundamentalCollector(revised).collect(session, asset)

    assert report.updated == 1

    from sqlalchemy import select

    from aidss.db.models import FundamentalMetric

    rows = session.scalars(select(FundamentalMetric)).all()
    assert len(rows) == 1
    assert rows[0].value == Decimal("19.1")


def test_a_provider_with_no_fundamentals_is_reported_as_unsupported(session) -> None:
    fixture = get_market_data_provider(Settings(market_data_provider="fixture"))
    asset = MarketDataCollector(fixture).get_or_create_asset(session, "BBCA")
    report = FundamentalCollector(fixture).collect(session, asset)

    assert report.unsupported
    assert report.fetched == 0


def test_the_base_interface_defaults_to_no_fundamentals() -> None:
    """Optional rather than abstract: most price feeds carry none."""
    fixture = get_market_data_provider(Settings(market_data_provider="fixture"))
    assert fixture.get_fundamentals("BBCA") == []
