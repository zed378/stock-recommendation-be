"""Alpha Vantage adapter, against a mocked transport and a recorded payload.

The interesting surface here is not the happy path. Alpha Vantage answers
**HTTP 200 for every failure** - bad symbol, exhausted quota, premium-only
endpoint - and writes missing numbers as the string ``"None"``. Both produce
silent corruption rather than an exception in an adapter that trusts the status
code, so both get more coverage than the parse that works.

`OVERVIEW_IBM` below is a real response, fetched from the live endpoint with
the documented demo key and trimmed only of the prose description. Testing
against invented JSON would test the invention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from aidss.domain.types import Timeframe
from aidss.plugins.adapters.market_alphavantage import AlphaVantageMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

# --- recorded payloads -----------------------------------------------------

OVERVIEW_IBM: dict[str, str] = {
    "Symbol": "IBM",
    "AssetType": "Common Stock",
    "Name": "International Business Machines",
    "Exchange": "NYSE",
    "Currency": "USD",
    "Country": "USA",
    "Sector": "TECHNOLOGY",
    "FiscalYearEnd": "December",
    "LatestQuarter": "2026-06-30",
    "MarketCapitalization": "210708349000",
    "EBITDA": "16473000000",
    "PERatio": "19.88",
    "PEGRatio": "2.269",
    "BookValue": "36.57",
    "DividendPerShare": "6.73",
    "DividendYield": "0.0304",
    "EPS": "11.25",
    "RevenuePerShareTTM": "73.7",
    "ProfitMargin": "0.155",
    "OperatingMarginTTM": "0.166",
    "ReturnOnAssetsTTM": "0.053",
    "ReturnOnEquityTTM": "0.345",
    "RevenueTTM": "69094998000",
    "GrossProfitTTM": "40143000000",
    "DilutedEPSTTM": "11.25",
    "QuarterlyEarningsGrowthYOY": "-0.018",
    "QuarterlyRevenueGrowthYOY": "0.011",
    "AnalystTargetPrice": "244.16",
    "AnalystRatingStrongBuy": "3",
    "AnalystRatingBuy": "12",
    "AnalystRatingHold": "7",
    "AnalystRatingSell": "0",
    "AnalystRatingStrongSell": "1",
    "TrailingPE": "19.88",
    "ForwardPE": "18.05",
    "PriceToSalesRatioTTM": "3.05",
    "PriceToBookRatio": "6.12",
    "EVToRevenue": "3.876",
    "EVToEBITDA": "15.24",
    "Beta": "0.675",
    "52WeekHigh": "332.46",
    "52WeekLow": "199.19",
    "50DayMovingAverage": "260.44",
    "200DayMovingAverage": "270.49",
    "SharesOutstanding": "942134000",
    "DividendDate": "2026-09-10",
    "ExDividendDate": "2026-08-10",
}

GLOBAL_QUOTE = {
    "Global Quote": {
        "01. symbol": "IBM",
        "02. open": "258.0000",
        "03. high": "262.5500",
        "04. low": "257.1200",
        "05. price": "261.3400",
        "06. volume": "3894621",
        "07. latest trading day": "2026-08-03",
        "08. previous close": "259.8800",
        "09. change": "1.4600",
        "10. change percent": "0.5618%",
    }
}

DAILY_SERIES = {
    "Meta Data": {
        "1. Information": "Daily Prices",
        "2. Symbol": "BBCA.JKT",
        "3. Last Refreshed": "2026-08-03",
        "4. Output Size": "Full size",
        "5. Time Zone": "US/Eastern",
    },
    # Newest first, the way Alpha Vantage sends it.
    "Time Series (Daily)": {
        "2026-08-03": {
            "1. open": "9500.0",
            "2. high": "9650.0",
            "3. low": "9475.0",
            "4. close": "9600.0",
            "5. volume": "51234500",
        },
        "2026-08-02": {
            "1. open": "9400.0",
            "2. high": "9525.0",
            "3. low": "9380.0",
            "4. close": "9500.0",
            "5. volume": "43112000",
        },
        "2026-08-01": {
            "1. open": "9350.0",
            "2. high": "9420.0",
            "3. low": "9300.0",
            "4. close": "9400.0",
            "5. volume": "39880100",
        },
    },
}

INTRADAY_SERIES = {
    "Meta Data": {
        "1. Information": "Intraday (5min) open, high, low, close prices and volume",
        "2. Symbol": "IBM",
        "6. Time Zone": "US/Eastern",
    },
    "Time Series (5min)": {
        "2026-08-03 16:00:00": {
            "1. open": "261.0",
            "2. high": "261.5",
            "3. low": "260.9",
            "4. close": "261.34",
            "5. volume": "120000",
        }
    },
}


# --- harness ---------------------------------------------------------------


def provider_returning(*payloads: object, suffix: str = ".JKT", premium: bool = False, **kwargs):
    """An adapter whose transport replays the given payloads in order.

    Request pacing is off unless a test asks for it: the real interval is over
    a second, and a suite that actually waited would take minutes to assert
    things that have nothing to do with timing.
    """
    queue = list(payloads)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0) if queue else {}
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://www.alphavantage.co"
    )
    kwargs.setdefault("min_request_interval", 0)
    adapter = AlphaVantageMarketDataProvider(
        "test-key", symbol_suffix=suffix, premium=premium, client=client, **kwargs
    )
    return adapter, seen


# --- construction and symbols ---------------------------------------------


def test_an_empty_key_is_refused_at_construction() -> None:
    """Better than a 200 carrying an "Information" body at collection time."""
    with pytest.raises(ValueError, match="API key"):
        AlphaVantageMarketDataProvider("")


def test_the_jakarta_suffix_is_jkt_not_jk() -> None:
    """Yahoo says BBCA.JK and Alpha Vantage says BBCA.JKT for the same asset."""
    adapter, _ = provider_returning()
    assert adapter.to_provider_symbol("bbca") == "BBCA.JKT"


def test_a_ticker_that_already_has_a_suffix_is_left_alone() -> None:
    adapter, _ = provider_returning()
    assert adapter.to_provider_symbol("BMW.DE") == "BMW.DE"


def test_an_empty_suffix_disables_the_mapping() -> None:
    adapter, _ = provider_returning(suffix="")
    assert adapter.to_provider_symbol("AAPL") == "AAPL"


def test_the_api_key_is_sent_but_never_in_the_path() -> None:
    adapter, seen = provider_returning(GLOBAL_QUOTE)
    adapter.get_quote("IBM")
    assert "apikey=test-key" in str(seen[0].url)
    assert "test-key" not in seen[0].url.path


# --- the 200-means-failure family -----------------------------------------


def test_a_quota_note_is_retryable() -> None:
    """The quota resets. Giving up permanently would lose tomorrow's run."""
    adapter, _ = provider_returning(
        {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls "
                 "per minute and 500 calls per day."}
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("BBCA")
    assert exc.value.retryable is True


def test_a_demo_key_restriction_is_not_retryable() -> None:
    """Retrying cannot fix it; the key has to change."""
    adapter, _ = provider_returning(
        {"Information": "The **demo** API key is for demo purposes only. Please claim your free "
                        "API key at (https://www.alphavantage.co/support/#api-key)"}
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("BBCA")
    assert exc.value.retryable is False


def test_a_daily_limit_reported_as_information_is_still_retryable() -> None:
    """Newer accounts get the quota message under `Information`, not `Note`.

    Classifying it as permanent would silently stop fundamentals collection
    for good on the first day the limit was reached.
    """
    adapter, _ = provider_returning(
        {"Information": "We have detected your API key and our standard API rate limit is 25 "
                        "requests per day."}
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("BBCA")
    assert exc.value.retryable is True


def test_an_invalid_symbol_is_permanent() -> None:
    adapter, _ = provider_returning(
        {"Error Message": "Invalid API call. Please retry or visit the documentation."}
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("NOSUCH")
    assert exc.value.retryable is False


def test_a_body_error_beats_the_status_code() -> None:
    """The whole point: 200 is not evidence of success from this API."""
    adapter, _ = provider_returning(httpx.Response(200, json={"Note": "throttled"}))
    with pytest.raises(ProviderUnavailableError):
        adapter.get_quote("IBM")


def test_a_non_json_body_names_itself() -> None:
    adapter, _ = provider_returning(httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ProviderUnavailableError, match="not JSON"):
        adapter.get_quote("IBM")


def test_a_json_array_is_rejected_rather_than_indexed() -> None:
    adapter, _ = provider_returning(httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(ProviderUnavailableError, match="JSON object"):
        adapter.get_quote("IBM")


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (403, False), (404, False)],
)
def test_http_status_codes_map_to_the_right_retryability(status: int, retryable: bool) -> None:
    adapter, _ = provider_returning(httpx.Response(status, json={}))
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_quote("IBM")
    assert exc.value.retryable is retryable


def test_a_transport_failure_is_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://www.alphavantage.co"
    )
    adapter = AlphaVantageMarketDataProvider("k", client=client)
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_quote("IBM")
    assert exc.value.retryable is True


# --- fundamentals ----------------------------------------------------------


def metrics(adapter, payload=OVERVIEW_IBM) -> dict[str, Decimal]:
    return {p.metric: p.value for p in adapter.get_fundamentals("IBM")}


def test_the_recorded_payload_parses_into_the_shared_vocabulary() -> None:
    """The metric names must match the Yahoo adapter's, or the two providers
    write rows that cannot be compared with each other."""
    adapter, _ = provider_returning(OVERVIEW_IBM)
    parsed = metrics(adapter)

    assert parsed["pe_ratio"] == Decimal("19.88")
    assert parsed["price_to_book"] == Decimal("6.12")
    assert parsed["ev_to_ebitda"] == Decimal("15.24")
    assert parsed["return_on_equity"] == Decimal("0.345")
    assert parsed["market_cap"] == Decimal("210708349000")
    assert parsed["eps_trailing"] == Decimal("11.25")


def test_a_negative_growth_figure_keeps_its_sign() -> None:
    """Dropping the minus would turn a contraction into growth."""
    adapter, _ = provider_returning(OVERVIEW_IBM)
    assert metrics(adapter)["earnings_growth"] == Decimal("-0.018")


def test_analyst_opinions_are_not_stored_as_fundamentals() -> None:
    """A target price is another firm's recommendation, not a reported figure.

    Storing it here would let a third party's conclusion enter the evidence
    base and be cited back as data.
    """
    adapter, _ = provider_returning(OVERVIEW_IBM)
    parsed = metrics(adapter)
    assert not any("analyst" in name or "target" in name for name in parsed)
    assert Decimal("244.16") not in parsed.values()


def test_price_statistics_are_not_stored_as_fundamentals() -> None:
    """The Indicator Engine computes these from candles; two sources drift."""
    adapter, _ = provider_returning(OVERVIEW_IBM)
    parsed = metrics(adapter)
    assert not any("moving_average" in name or "52_week" in name for name in parsed)
    assert Decimal("270.49") not in parsed.values()


def test_the_period_is_the_reporting_quarter_not_today() -> None:
    """A today-stamp hides that one asset's figures are a quarter staler."""
    adapter, _ = provider_returning(OVERVIEW_IBM)
    points = adapter.get_fundamentals("IBM")
    assert {p.period.isoformat() for p in points} == {"2026-06-30"}
    assert {p.period_type for p in points} == {"ttm"}


def test_a_missing_latest_quarter_falls_back_to_today() -> None:
    payload = {k: v for k, v in OVERVIEW_IBM.items() if k != "LatestQuarter"}
    adapter, _ = provider_returning(payload)
    points = adapter.get_fundamentals("IBM")
    assert points
    assert points[0].period == datetime.now(UTC).date()


def test_the_string_none_is_absent_not_a_parse_error() -> None:
    """Alpha Vantage writes missing values as "None". Decimal("None") raises,
    and one missing field must not take out the whole payload."""
    payload = {**OVERVIEW_IBM, "PERatio": "None", "PEGRatio": "-", "Beta": ""}
    adapter, _ = provider_returning(payload)
    parsed = metrics(adapter)

    assert "pe_ratio" not in parsed
    assert "peg_ratio" not in parsed
    assert "beta" not in parsed
    assert parsed["price_to_book"] == Decimal("6.12")  # the rest survived


def test_an_empty_overview_means_no_coverage_not_a_failure() -> None:
    """Alpha Vantage returns `{}` for symbols it does not cover, which is a
    real outcome for an IDX ticker. The collector reports it as unsupported."""
    adapter, _ = provider_returning({})
    assert adapter.get_fundamentals("BBCA") == []


def test_fundamentals_are_attributed_to_this_adapter() -> None:
    adapter, _ = provider_returning()
    assert adapter.fundamentals_source_name() == "alphavantage"


# --- quotes ----------------------------------------------------------------


def test_a_quote_parses_price_and_previous_close() -> None:
    adapter, _ = provider_returning(GLOBAL_QUOTE)
    quote = adapter.get_quote("ibm")

    assert quote.ticker == "IBM"
    assert quote.price == Decimal("261.3400")
    assert quote.previous_close == Decimal("259.8800")
    assert quote.timestamp == datetime(2026, 8, 3, tzinfo=UTC)


def test_an_unknown_symbol_yields_an_empty_quote_block() -> None:
    """No error key - emptiness is the only signal there is."""
    adapter, _ = provider_returning({"Global Quote": {}})
    with pytest.raises(ProviderUnavailableError, match="no quote available"):
        adapter.get_quote("NOSUCH")


def test_a_quote_without_a_price_is_an_error_not_a_zero() -> None:
    payload = {"Global Quote": {**GLOBAL_QUOTE["Global Quote"], "05. price": "None"}}
    adapter, _ = provider_returning(payload)
    with pytest.raises(ProviderUnavailableError, match="no price"):
        adapter.get_quote("IBM")


# --- candles ---------------------------------------------------------------


WINDOW = (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 4, tzinfo=UTC))


def test_daily_candles_come_back_in_ascending_order() -> None:
    """Alpha Vantage sends newest first; the contract says ascending."""
    adapter, _ = provider_returning(DAILY_SERIES)
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)

    assert [c.timestamp.date().isoformat() for c in candles] == [
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
    ]
    assert candles[-1].close == Decimal("9600.0")
    assert candles[-1].volume == Decimal("51234500")


def test_the_requested_window_is_enforced_client_side() -> None:
    """`outputsize=full` returns everything; the range is ours to apply."""
    adapter, _ = provider_returning(DAILY_SERIES)
    candles = adapter.get_historical_candles(
        "BBCA", Timeframe.D1,
        datetime(2026, 8, 2, tzinfo=UTC),
        datetime(2026, 8, 2, 23, 59, tzinfo=UTC),
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal("9500.0")


def test_an_intraday_stamp_is_converted_from_exchange_local_time() -> None:
    """The stamps are naive local time and the zone is only in Meta Data.

    Treating them as UTC would shift every bar by the exchange's offset -
    four hours here - producing a chart that looks fine and is wrong.
    """
    adapter, _ = provider_returning(INTRADAY_SERIES)
    candles = adapter.get_historical_candles(
        "IBM", Timeframe.M5,
        datetime(2026, 8, 3, tzinfo=UTC),
        datetime(2026, 8, 4, tzinfo=UTC),
    )
    assert len(candles) == 1
    # 16:00 US/Eastern on 3 August is 20:00 UTC.
    assert candles[0].timestamp == datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def test_a_malformed_bar_drops_itself_rather_than_the_request() -> None:
    payload = {
        **DAILY_SERIES,
        "Time Series (Daily)": {
            **DAILY_SERIES["Time Series (Daily)"],
            "2026-07-31": {"1. open": "None", "2. high": "1", "3. low": "1", "4. close": "1"},
            "not-a-date": {"1. open": "1", "2. high": "1", "3. low": "1", "4. close": "1"},
        },
    }
    adapter, _ = provider_returning(payload)
    candles = adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)
    assert len(candles) == 3


def test_an_unsupported_timeframe_is_refused_by_name() -> None:
    adapter, _ = provider_returning(DAILY_SERIES)
    with pytest.raises(ValueError, match="not offered by Alpha Vantage"):
        adapter.get_historical_candles("BBCA", Timeframe.H4, *WINDOW)


def test_naive_datetimes_are_refused() -> None:
    adapter, _ = provider_returning(DAILY_SERIES)
    with pytest.raises(ValueError, match="timezone-aware"):
        adapter.get_historical_candles(
            "BBCA", Timeframe.D1, datetime(2026, 7, 1), datetime(2026, 8, 1)
        )


def test_a_reversed_window_is_refused() -> None:
    adapter, _ = provider_returning(DAILY_SERIES)
    with pytest.raises(ValueError, match="must not be after"):
        adapter.get_historical_candles("BBCA", Timeframe.D1, WINDOW[1], WINDOW[0])


def test_a_missing_series_key_names_what_was_expected() -> None:
    """A renamed key must report itself, not surface as an empty result."""
    adapter, _ = provider_returning({"Meta Data": {}})
    with pytest.raises(ProviderUnavailableError, match="Time Series \\(Daily\\)"):
        adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)


def test_realtime_is_not_claimed() -> None:
    adapter, _ = provider_returning()
    assert adapter.supports_realtime() is False


# --- free-tier entitlements ------------------------------------------------
#
# Both of these were found by running against a real free key, not by reading
# the documentation, which describes neither.


def test_a_free_key_asks_for_compact_not_full() -> None:
    """`outputsize=full` is premium, and asking for it on a free key is
    *refused* rather than downgraded - so the request returns nothing at all
    instead of less. The adapter asked for `full` until a live run said so."""
    adapter, seen = provider_returning(DAILY_SERIES)
    adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)
    assert "outputsize=compact" in str(seen[0].url)


def test_a_premium_key_asks_for_full() -> None:
    adapter, seen = provider_returning(DAILY_SERIES, premium=True)
    adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)
    assert "outputsize=full" in str(seen[0].url)


def test_the_premium_setting_reaches_intraday_too() -> None:
    adapter, seen = provider_returning(INTRADAY_SERIES, premium=True)
    adapter.get_historical_candles(
        "IBM", Timeframe.M5, datetime(2026, 8, 3, tzinfo=UTC), datetime(2026, 8, 4, tzinfo=UTC)
    )
    assert "outputsize=full" in str(seen[0].url)


def test_the_premium_refusal_is_reported_as_permanent() -> None:
    """A plan does not change by waiting, so retrying only spends allowance."""
    adapter, _ = provider_returning(
        {"Information": "Thank you for using Alpha Vantage! The outputsize=full parameter "
                        "value is a premium feature for the TIME_SERIES_DAILY endpoint."}
    )
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_historical_candles("BBCA", Timeframe.D1, *WINDOW)
    assert exc.value.retryable is False


# --- request pacing --------------------------------------------------------


class FakeClock:
    """A clock that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_consecutive_requests_are_spaced_apart() -> None:
    """The free tier also caps requests per second and mentions it only in the
    refusal. Four calls in a row is enough to trip it, which is how a live run
    of this file's own tests discovered the limit."""
    clock = FakeClock()
    adapter, _ = provider_returning(
        GLOBAL_QUOTE, GLOBAL_QUOTE, GLOBAL_QUOTE,
        min_request_interval=1.2, clock=clock, sleep=clock.sleep,
    )

    adapter.get_quote("IBM")
    adapter.get_quote("IBM")
    adapter.get_quote("IBM")

    assert clock.slept == [1.2, 1.2], "the second and third requests should have waited"


def test_the_first_request_does_not_wait() -> None:
    clock = FakeClock()
    adapter, _ = provider_returning(
        GLOBAL_QUOTE, min_request_interval=1.2, clock=clock, sleep=clock.sleep
    )
    adapter.get_quote("IBM")
    assert clock.slept == []


def test_time_already_elapsed_counts_towards_the_interval() -> None:
    """A caller that was slow anyway should not be made slower."""
    clock = FakeClock()
    adapter, _ = provider_returning(
        GLOBAL_QUOTE, GLOBAL_QUOTE,
        min_request_interval=1.2, clock=clock, sleep=clock.sleep,
    )
    adapter.get_quote("IBM")
    clock.now += 5.0  # the caller did something else for five seconds
    adapter.get_quote("IBM")
    assert clock.slept == []
