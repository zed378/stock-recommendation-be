"""Yahoo Finance adapter tests.

Every test here runs against a mocked transport. Hitting the live endpoint in
a unit suite would make the build depend on a third party's uptime and rate
limits, and would turn "the parser is correct" into "Yahoo answered today".

The live check lives in ``test_yahoo_live.py`` behind an opt-in marker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from aidss.config import Settings
from aidss.domain.types import Timeframe
from aidss.plugins.adapters.market_yahoo import YahooMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.registry import get_market_data_provider

START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 10, tzinfo=UTC)


def chart_payload(
    *,
    timestamps: list[int] | None = None,
    opens: list | None = None,
    highs: list | None = None,
    lows: list | None = None,
    closes: list | None = None,
    volumes: list | None = None,
    meta: dict | None = None,
) -> dict:
    """A response in the shape the live endpoint returns."""
    timestamps = timestamps if timestamps is not None else [1735689600, 1735776000]
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": meta
                    or {
                        "symbol": "BBCA.JK",
                        "regularMarketPrice": 9525.0,
                        "chartPreviousClose": 9500.0,
                        "regularMarketTime": 1735776000,
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens if opens is not None else [9500.0, 9525.0],
                                "high": highs if highs is not None else [9575.0, 9600.0],
                                "low": lows if lows is not None else [9450.0, 9500.0],
                                "close": closes if closes is not None else [9525.0, 9550.0],
                                "volume": volumes if volumes is not None else [12000000, 9500000],
                            }
                        ]
                    },
                }
            ],
        }
    }


def provider_returning(payload: dict, *, status: int = 200, **kwargs) -> YahooMarketDataProvider:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        captured["headers"] = request.headers
        if isinstance(payload, str):
            return httpx.Response(status, text=payload)
        return httpx.Response(status, json=payload)

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=YahooMarketDataProvider.BASE_URL,
        headers={"User-Agent": "test-agent"},
    )
    adapter = YahooMarketDataProvider(client=client, **kwargs)
    adapter.captured = captured  # type: ignore[attr-defined]
    return adapter


# --- Symbol mapping --------------------------------------------------------


def test_idx_tickers_get_the_jakarta_suffix() -> None:
    adapter = YahooMarketDataProvider(client=httpx.Client())
    assert adapter.to_yahoo_symbol("BBCA") == "BBCA.JK"
    assert adapter.to_yahoo_symbol("bbca") == "BBCA.JK"


def test_a_ticker_that_already_carries_a_suffix_is_left_alone() -> None:
    """So a non-IDX asset can be stored with its explicit Yahoo symbol."""
    adapter = YahooMarketDataProvider(client=httpx.Client())
    assert adapter.to_yahoo_symbol("BMW.DE") == "BMW.DE"


def test_an_empty_suffix_disables_the_mapping() -> None:
    adapter = YahooMarketDataProvider(symbol_suffix="", client=httpx.Client())
    assert adapter.to_yahoo_symbol("AAPL") == "AAPL"


def test_suffix_comes_from_settings() -> None:
    adapter = YahooMarketDataProvider.from_settings(Settings(yahoo_symbol_suffix=".AX"))
    assert adapter.to_yahoo_symbol("BHP") == "BHP.AX"


# --- Parsing ---------------------------------------------------------------


def test_candles_are_parsed_into_domain_types() -> None:
    adapter = provider_returning(chart_payload())
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)

    assert len(candles) == 2
    first = candles[0]
    assert first.open == Decimal("9500.0")
    assert first.high == Decimal("9575.0")
    assert first.close == Decimal("9525.0")
    assert first.volume == Decimal("12000000")
    assert first.timestamp.tzinfo is not None


def test_floats_are_converted_without_binary_artefacts() -> None:
    """Decimal(str(x)) rather than Decimal(x): 0.1 must stay 0.1."""
    adapter = provider_returning(
        chart_payload(timestamps=[1735689600], opens=[0.1], highs=[0.3], lows=[0.1], closes=[0.2],
                      volumes=[100])
    )
    candle = adapter.get_historical_candles("GOTO", Timeframe.D1, START, END)[0]
    assert candle.open == Decimal("0.1")


def test_null_bars_are_dropped_not_zero_filled() -> None:
    """Yahoo emits nulls for halted sessions.

    A zero-filled bar would reach the Indicator Engine and drag every average
    through it; a gap is the honest representation.
    """
    adapter = provider_returning(
        chart_payload(
            timestamps=[1, 2, 3],
            opens=[100.0, None, 102.0],
            highs=[101.0, None, 103.0],
            lows=[99.0, None, 101.0],
            closes=[100.5, None, 102.5],
            volumes=[1000, None, 1200],
        )
    )
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert len(candles) == 2
    assert all(c.open > 0 for c in candles)


def test_a_missing_volume_becomes_zero_rather_than_dropping_the_bar() -> None:
    adapter = provider_returning(
        chart_payload(timestamps=[1], opens=[100.0], highs=[101.0], lows=[99.0], closes=[100.5],
                      volumes=[None])
    )
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert len(candles) == 1
    assert candles[0].volume == Decimal("0")


def test_an_empty_result_yields_no_candles() -> None:
    adapter = provider_returning(chart_payload(timestamps=[], opens=[], highs=[], lows=[],
                                               closes=[], volumes=[]))
    assert adapter.get_historical_candles("BBCA", Timeframe.D1, START, END) == []


def test_quote_is_read_from_the_meta_block() -> None:
    adapter = provider_returning(chart_payload())
    quote = adapter.get_quote("BBCA")
    assert quote.ticker == "BBCA"
    assert quote.price == Decimal("9525.0")
    assert quote.previous_close == Decimal("9500.0")


# --- Request construction --------------------------------------------------


def test_the_request_carries_the_mapped_symbol_and_range() -> None:
    adapter = provider_returning(chart_payload())
    adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)

    url = adapter.captured["url"]  # type: ignore[attr-defined]
    assert "BBCA.JK" in str(url.path)
    assert url.params["interval"] == "1d"
    assert int(url.params["period1"]) == int(START.timestamp())
    assert int(url.params["period2"]) == int(END.timestamp())


@pytest.mark.parametrize(
    ("timeframe", "interval"),
    [
        (Timeframe.M5, "5m"),
        (Timeframe.H1, "1h"),
        (Timeframe.D1, "1d"),
        (Timeframe.W1, "1wk"),
        (Timeframe.MN1, "1mo"),
    ],
)
def test_timeframes_map_to_yahoo_intervals(timeframe: Timeframe, interval: str) -> None:
    adapter = provider_returning(chart_payload())
    adapter.get_historical_candles("BBCA", timeframe, START, END)
    assert adapter.captured["url"].params["interval"] == interval  # type: ignore[attr-defined]


def test_an_unsupported_timeframe_is_rejected_rather_than_substituted() -> None:
    """Yahoo has no 4-hour interval; quietly serving 1h would be worse."""
    adapter = provider_returning(chart_payload())
    with pytest.raises(ValueError, match="not offered by Yahoo"):
        adapter.get_historical_candles("BBCA", Timeframe.H4, START, END)


def test_naive_datetimes_are_rejected() -> None:
    adapter = provider_returning(chart_payload())
    with pytest.raises(ValueError, match="aware"):
        adapter.get_historical_candles(
            "BBCA", Timeframe.D1, datetime(2025, 1, 1), datetime(2025, 2, 1)
        )


# --- Failure handling ------------------------------------------------------


def test_rate_limiting_is_reported_as_retryable() -> None:
    """No published limit, so backing off is the only sane response."""
    adapter = provider_returning({}, status=429)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert excinfo.value.retryable


def test_access_refusal_is_reported_as_not_retryable() -> None:
    """403 from an unofficial endpoint means the rules changed; retrying will not help."""
    adapter = provider_returning({}, status=403)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert not excinfo.value.retryable
    assert "access rules" in str(excinfo.value)


def test_server_errors_are_retryable() -> None:
    adapter = provider_returning({}, status=503)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert excinfo.value.retryable


def test_an_unknown_symbol_is_not_retryable() -> None:
    adapter = provider_returning({}, status=404)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_historical_candles("NOSUCH", Timeframe.D1, START, END)
    assert not excinfo.value.retryable


def test_an_upstream_error_object_is_surfaced() -> None:
    payload = {
        "chart": {
            "error": {"code": "Not Found", "description": "No data found"},
            "result": None,
        }
    }
    adapter = provider_returning(payload)
    with pytest.raises(ProviderUnavailableError, match="No data found"):
        adapter.get_historical_candles("NOSUCH", Timeframe.D1, START, END)


def test_a_changed_response_shape_reports_itself() -> None:
    """The endpoint is undocumented, so it will change.

    When it does, the failure should name the problem rather than surface as a
    KeyError several layers away from the cause.
    """
    adapter = provider_returning({"unexpected": "shape"})
    with pytest.raises(ProviderUnavailableError, match="unexpected response shape"):
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)


def test_an_html_error_page_is_reported_clearly() -> None:
    """An unofficial endpoint returns HTML when it is unhappy, not JSON."""
    adapter = provider_returning("<html><body>Too Many Requests</body></html>")
    with pytest.raises(ProviderUnavailableError, match="not JSON"):
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)


def test_a_network_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = YahooMarketDataProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(handler), base_url=YahooMarketDataProvider.BASE_URL
        )
    )
    with pytest.raises(ProviderUnavailableError) as excinfo:
        adapter.get_historical_candles("BBCA", Timeframe.D1, START, END)
    assert excinfo.value.retryable


# --- Honesty about what the source is --------------------------------------


def test_the_adapter_does_not_claim_realtime() -> None:
    """The public endpoint is delayed; claiming otherwise would mislead callers."""
    assert YahooMarketDataProvider(client=httpx.Client()).supports_realtime() is False


def test_the_adapter_resolves_through_configuration() -> None:
    provider = get_market_data_provider(Settings(market_data_provider="yahoo"))
    assert isinstance(provider, YahooMarketDataProvider)


# --- Integration with the collector ---------------------------------------


def test_collector_stores_candles_fetched_from_yahoo(session) -> None:
    """The parsed output survives validation and normalisation end to end."""
    from aidss.collectors.market_data import MarketDataCollector, load_candles

    base = int(datetime(2025, 1, 6, tzinfo=UTC).timestamp())
    day = 86400
    adapter = provider_returning(
        chart_payload(
            timestamps=[base, base + day, base + 2 * day],
            opens=[9500.0, 9525.0, 9540.0],
            highs=[9575.0, 9600.0, 9610.0],
            lows=[9450.0, 9500.0, 9520.0],
            closes=[9525.0, 9550.0, 9560.0],
            volumes=[12_000_000, 9_500_000, 8_100_000],
        )
    )

    collector = MarketDataCollector(adapter)
    asset = collector.get_or_create_asset(session, "BBCA")
    report = collector.collect(
        session,
        asset,
        Timeframe.D1,
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 31, tzinfo=UTC),
    )

    assert report.fetched == 3
    assert report.inserted == 3
    assert report.rejected == 0
    assert len(load_candles(session, asset.id, Timeframe.D1)) == 3


def test_payload_helper_matches_the_documented_shape() -> None:
    """Guards the fixture itself: a wrong fixture makes every test above vacuous."""
    payload = chart_payload()
    parsed = json.loads(json.dumps(payload))
    result = parsed["chart"]["result"][0]
    assert "timestamp" in result
    assert "open" in result["indicators"]["quote"][0]
    assert "regularMarketPrice" in result["meta"]
