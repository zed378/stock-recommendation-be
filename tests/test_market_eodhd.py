"""EODHD adapter against canned responses in the shape EODHD's fundamentals page describes.

No call is made to EODHD. The shapes are from its documentation, not from a live key, so a
first real call may still surprise (see the module docstring and `test_eodhd_live.py`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from aidss.config import Settings
from aidss.plugins.adapters.market_eodhd import EODHDMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

KEY = "tok-secret-123"

PAYLOAD = {
    "General": {"Code": "BBCA", "CurrencyCode": "IDR"},
    "Highlights": {
        "MostRecentQuarter": "2026-09-30",
        "PERatio": 17.5,
        "ReturnOnEquityTTM": "0.21",
        "MarketCapitalization": 1100000000000000,
        "EarningsShare": "None",
        "WallStreetTargetPrice": 12000,
    },
    "Valuation": {"ForwardPE": 16.1, "PriceBookMRQ": 4.2},
    "SharesStats": {"SharesOutstanding": 123000000000},
    "Technicals": {"Beta": 0.9, "52WeekHigh": 11000},
}


def adapter(handler, **kw) -> tuple[EODHDMarketDataProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(base_url="https://eodhd.com", transport=httpx.MockTransport(wrapped))
    return EODHDMarketDataProvider(KEY, client=client, min_request_interval=0, **kw), seen


def ok(payload):
    return lambda request: httpx.Response(200, json=payload)


def test_metrics_use_the_shared_vocabulary_and_the_reported_quarter() -> None:
    provider, seen = adapter(ok(PAYLOAD))
    points = {p.metric: p for p in provider.get_fundamentals("BBCA")}
    assert points["pe_ratio"].value == Decimal("17.5")
    assert points["return_on_equity"].value == Decimal("0.21")
    assert points["forward_pe_ratio"].value == Decimal("16.1")
    assert points["shares_outstanding"].value == Decimal("123000000000")
    assert points["beta"].value == Decimal("0.9")
    assert {p.period for p in points.values()} == {date(2026, 9, 30)}
    assert {p.period_type for p in points.values()} == {"ttm"}
    assert seen[0].url.path.endswith("/fundamentals/BBCA.JK")


def test_missing_values_are_skipped_and_opinions_and_price_stats_are_never_stored() -> None:
    provider, _ = adapter(ok(PAYLOAD))
    metrics = {p.metric for p in provider.get_fundamentals("BBCA")}
    assert "eps_trailing" not in metrics  # the string "None" is absence, not a value
    assert metrics.isdisjoint({"analyst_target_price", "wall_street_target_price"})
    assert not any("52" in m or "week" in m for m in metrics)


def test_an_unknown_symbol_is_no_coverage_not_a_failure() -> None:
    provider, _ = adapter(lambda r: httpx.Response(404, text="Not Found"))
    assert provider.get_fundamentals("ZZZZ") == []
    provider, _ = adapter(ok({}))
    assert provider.get_fundamentals("ZZZZ") == []


def test_a_suffix_already_present_is_not_doubled() -> None:
    provider, seen = adapter(ok(PAYLOAD))
    provider.get_fundamentals("bbca.jk")
    assert seen[0].url.path.endswith("/fundamentals/BBCA.JK")


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(401, False), (403, False), (402, True), (429, True), (500, True), (418, False)],
)
def test_status_codes_map_to_retryable_or_permanent(status: int, retryable: bool) -> None:
    provider, _ = adapter(lambda r: httpx.Response(status, text="x"))
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.get_fundamentals("BBCA")
    assert caught.value.retryable is retryable


def test_the_token_never_appears_in_an_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    provider, _ = adapter(boom)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.get_fundamentals("BBCA")
    assert KEY not in str(caught.value)
    assert "<token>" in str(caught.value)


def test_a_non_idr_report_is_refused_rather_than_mixed() -> None:
    payload = {**PAYLOAD, "General": {"CurrencyCode": "USD"}}
    provider, _ = adapter(ok(payload))
    with pytest.raises(ProviderUnavailableError, match="not IDR") as caught:
        provider.get_fundamentals("BBCA")
    assert caught.value.retryable is False


def test_a_body_that_is_not_an_object_is_refused() -> None:
    provider, _ = adapter(ok([1, 2]))
    with pytest.raises(ProviderUnavailableError, match="expected a JSON object"):
        provider.get_fundamentals("BBCA")


def test_prices_are_not_served_and_the_message_says_how_to_get_them() -> None:
    provider, _ = adapter(ok(PAYLOAD))
    with pytest.raises(ProviderUnavailableError, match="composite"):
        provider.get_quote("BBCA")


def test_it_refuses_to_construct_without_a_key() -> None:
    with pytest.raises(ValueError, match="AIDSS_EODHD_API_KEY"):
        EODHDMarketDataProvider.from_settings(Settings())
    with pytest.raises(ValueError):
        EODHDMarketDataProvider("")


def test_the_key_comes_from_settings_and_the_composite_can_name_it() -> None:
    from aidss.plugins.adapters.market_composite import CompositeMarketDataProvider

    settings = Settings(
        eodhd_api_key=KEY,
        composite_price_provider="fixture",
        composite_fundamentals_provider="eodhd",
    )
    composite = CompositeMarketDataProvider.from_settings(settings)
    assert composite.describe()["fundamentals"] == "eodhd"
    assert composite.fundamentals_source_name() == "eodhd"
