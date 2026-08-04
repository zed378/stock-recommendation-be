"""IDX fundamentals adapter, against a mocked transport and recorded rows.

Most of this file is about units, because units are where this provider is
dangerous. Nothing in the payload says that money is in billions of rupiah or
that `roe` is a percentage; both were established by comparing issuers across
three orders of magnitude against known figures. A mistake in either direction
is a silent hundred- or billion-fold error in a column that other providers
also write to, and no type check or schema catches it.

`BBCA_ROW` and `ADRO_ROW` are real responses from the live endpoint, trimmed to
the fields the adapter reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aidss.domain.types import Timeframe
from aidss.plugins.adapters.market_idx import IDXMarketDataProvider
from aidss.plugins.errors import ProviderUnavailableError

# --- recorded rows ---------------------------------------------------------

BBCA_ROW = {
    "code": "BBCA",
    "stockName": "Bank Central Asia Tbk.",
    "sector": "Financials",
    "fsDate": "2025-10-20",  # a *filing* date, not a period end - see below
    "fiscalYearEnd": "Dec",
    "assets": 1538501.81,
    "liabilities": 1251857.12,
    "equity": 276635.41,
    "sales": 77140.9,
    "ebt": 53766.94,
    "profitPeriod": 43413.46,
    "profitAttrOwner": 43397.42,
    "eps": 463.68,
    "bookValue": 2266.72,
    "per": 17.42,
    "priceBV": 3.56,
    "deRatio": 4.53,
    "roa": 3.7153,
    "roe": 20.6625,
    "npm": 74.098,
}

ADRO_ROW = {
    "code": "ADRO",
    "stockName": "Alamtri Resources Indonesia Tbk.",
    "sector": "Energy",
    "fsDate": "2025-10-31",
    "fiscalYearEnd": "Dec",
    "assets": 110084.52,
    "liabilities": 24011.36,
    "equity": 86073.17,
    "sales": 22503.79,
    "ebt": 7030.35,
    "profitPeriod": 5550.34,
    "profitAttrOwner": 5034.14,
    "eps": 320.6,
    "bookValue": 2928.69,
    "per": 5.65,
    "priceBV": 0.62,
    "deRatio": 0.28,
    "roa": 8.5591,
    "roe": 10.9468,
    "npm": 41.8697,
}


class FakeResponse:
    def __init__(self, payload, *, status: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class FakeSession:
    """Replays payloads and records every request."""

    def __init__(self, *payloads) -> None:
        self._queue = list(payloads)
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        item = self._queue.pop(0) if self._queue else {"data": []}
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, FakeResponse) else FakeResponse(item)


def provider(*payloads, **kwargs) -> tuple[IDXMarketDataProvider, FakeSession]:
    session = FakeSession(*payloads)
    kwargs.setdefault("min_request_interval", 0)
    return IDXMarketDataProvider(session=session, **kwargs), session


def metrics(adapter, ticker: str = "BBCA") -> dict[str, Decimal]:
    return {p.metric: p.value for p in adapter.get_fundamentals(ticker)}


# --- units: the reason this file exists ------------------------------------


def test_money_is_converted_from_billions_of_rupiah() -> None:
    """BBCA's assets arrive as 1538501.81, meaning Rp 1,538 trillion.

    Stored raw, beside Alpha Vantage's absolute figures, the two are a billion
    apart in the same column.
    """
    adapter, _ = provider({"data": [BBCA_ROW]})
    assert metrics(adapter)["total_assets"] == Decimal("1538501.81") * Decimal("1e9")


def test_the_scale_holds_for_a_small_issuer_too() -> None:
    """A per-issuer scale would be worse than a wrong one, because it would be
    right often enough to look correct."""
    tiny = {**BBCA_ROW, "code": "AIMS", "assets": 4.06, "equity": 0.96}
    adapter, _ = provider({"data": [tiny]})
    assert metrics(adapter, "AIMS")["total_assets"] == Decimal("4.06") * Decimal("1e9")


def test_percentages_are_converted_to_fractions() -> None:
    """IDX says 20.6625 and Alpha Vantage says 0.345 for the same concept.

    Every threshold rule downstream reads this column without asking which
    provider filled it.
    """
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)
    assert parsed["return_on_equity"] == Decimal("20.6625") / 100
    assert parsed["return_on_assets"] == Decimal("3.7153") / 100


def test_plain_ratios_are_left_alone() -> None:
    """PE and PBV are already unitless; dividing them by a hundred would be
    the same class of error in the other direction."""
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)
    assert parsed["pe_ratio"] == Decimal("17.42")
    assert parsed["price_to_book"] == Decimal("3.56")
    assert parsed["debt_to_equity"] == Decimal("4.53")


def test_per_share_figures_are_already_in_rupiah() -> None:
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)
    assert parsed["eps_trailing"] == Decimal("463.68")
    assert parsed["book_value_per_share"] == Decimal("2266.72")


def test_converted_values_stay_internally_consistent() -> None:
    """A sanity check the conversions cannot pass by accident: after scaling,
    liabilities over equity must still reproduce the reported ratio."""
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)
    derived = parsed["total_liabilities"] / parsed["total_equity"]
    assert abs(derived - parsed["debt_to_equity"]) < Decimal("0.01")


# --- what is deliberately not stored ---------------------------------------


def test_idx_net_profit_margin_is_not_stored_as_profit_margin() -> None:
    """IDX reports 74.1% while `profitAttrOwner / sales` from the same row is
    56.3%, so it is derived from a different denominator.

    Filing two different calculations under one name produces comparisons that
    look valid and are not. Both inputs are stored, so a consistent margin can
    be derived where it is wanted.
    """
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)

    assert "profit_margin" not in parsed
    assert parsed["net_income"] / parsed["total_revenue"] < Decimal("0.6")


def test_profit_including_minorities_is_not_stored_beside_the_one_that_excludes_them() -> None:
    adapter, _ = provider({"data": [BBCA_ROW]})
    parsed = metrics(adapter)
    assert parsed["net_income"] == Decimal("43397.42") * Decimal("1e9")
    assert Decimal("43411.05") * Decimal("1e9") not in parsed.values()


# --- period identity -------------------------------------------------------


def test_the_period_is_the_fiscal_year_end_not_the_reported_date() -> None:
    """`fsDate` is not what it sounds like.

    For fiscal 2024 IDX returns a period end; for fiscal 2025 it returns
    2025-10-20, a filing date. Keying on it would make every refetch look like
    a new period rather than a revision of the same one, and the collector's
    upsert would pile up near-duplicates instead of replacing a restated
    figure.
    """
    adapter, _ = provider({"data": [BBCA_ROW]})
    points = adapter.get_fundamentals("BBCA")
    year = datetime.now(UTC).year
    assert {p.period for p in points} == {datetime(year, 12, 31).date()}


def test_a_mid_year_filing_is_year_to_date_not_annual() -> None:
    """A statement filed in October carries nine months of revenue. Calling it
    annual overstates by a third; quarterly understates threefold."""
    adapter, _ = provider({"data": [BBCA_ROW]})
    assert {p.period_type for p in adapter.get_fundamentals("BBCA")} == {"ytd"}


def test_a_filing_after_the_year_end_is_annual() -> None:
    """Filed in April for the fiscal year that closed in December - the
    cumulative figure and the annual figure are then the same number."""
    year = datetime.now(UTC).year
    row = {**BBCA_ROW, "fsDate": f"{year + 1}-04-05"}
    adapter, _ = provider({"data": [row]})
    assert {p.period_type for p in adapter.get_fundamentals("BBCA")} == {"annual"}


def test_a_non_december_fiscal_year_end_is_respected() -> None:
    year = datetime.now(UTC).year
    row = {**BBCA_ROW, "fiscalYearEnd": "Jun", "fsDate": f"{year}-03-31"}
    adapter, _ = provider({"data": [row]})
    points = adapter.get_fundamentals("BBCA")
    assert points[0].period == datetime(year, 6, 30).date()
    assert points[0].period_type == "ytd"


def test_a_row_without_a_usable_date_names_the_problem() -> None:
    adapter, _ = provider({"data": [{**BBCA_ROW, "fsDate": None}]})
    with pytest.raises(ProviderUnavailableError, match="fsDate"):
        adapter.get_fundamentals("BBCA")


# --- matching the right issuer ---------------------------------------------


def test_the_ticker_is_matched_exactly_not_by_substring() -> None:
    """`search` is a substring filter: querying BBCA also returns BBCAP.

    A near-miss ticker is the worst possible thing to file under the right one.
    """
    adapter, _ = provider({"data": [{**BBCA_ROW, "code": "BBCAP"}]}, {"data": []}, {"data": []})
    assert adapter.get_fundamentals("BBCA") == []


def test_the_right_row_is_picked_out_of_several() -> None:
    adapter, _ = provider({"data": [{**BBCA_ROW, "code": "BBCAP"}, BBCA_ROW]})
    assert metrics(adapter)["pe_ratio"] == Decimal("17.42")


def test_an_unknown_ticker_reports_no_coverage_rather_than_failing(  # noqa: E501
) -> None:
    """The collector reports this as `unsupported`, which it is."""
    adapter, session = provider({"data": []}, {"data": []}, {"data": []})
    assert adapter.get_fundamentals("NOSUCH") == []
    assert len(session.calls) == 3, "should have walked back through recent years"


def test_an_empty_current_year_falls_back_to_the_previous_one() -> None:
    """The current fiscal year has no data until the first quarter is filed,
    and an empty result then would read as "IDX does not cover this issuer"."""
    adapter, session = provider({"data": []}, {"data": [ADRO_ROW]})
    parsed = metrics(adapter, "ADRO")

    assert parsed["pe_ratio"] == Decimal("5.65")
    assert [c["params"]["periodYear"] for c in session.calls] == [
        datetime.now(UTC).year,
        datetime.now(UTC).year - 1,
    ]


def test_the_walk_back_is_bounded() -> None:
    """Without a limit a delisted ticker would walk back forever."""
    adapter, session = provider(*[{"data": []}] * 10)
    adapter.get_fundamentals("GONE")
    assert len(session.calls) == 3


# --- transport and failure modes -------------------------------------------


def test_the_referer_the_endpoint_expects_is_sent() -> None:
    """Omitting it gets the request refused. Not a disguise - the request does
    originate from this application - but the API expects its own page."""
    adapter, session = provider({"data": [BBCA_ROW]})
    adapter.get_fundamentals("BBCA")
    assert "idx.co.id" in session.calls[0]["headers"]["Referer"]


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (403, False), (401, False), (404, False)],
)
def test_status_codes_map_to_the_right_retryability(status: int, retryable: bool) -> None:
    adapter, _ = provider(FakeResponse({}, status=status))
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("BBCA")
    assert exc.value.retryable is retryable


def test_a_refusal_names_the_most_likely_cause() -> None:
    """This adapter's single likeliest failure is the bot protection being
    tightened past what impersonation clears. Reporting that as an ordinary
    client error would send someone looking in the wrong place."""
    adapter, _ = provider(FakeResponse({}, status=403))
    with pytest.raises(ProviderUnavailableError, match="bot protection"):
        adapter.get_fundamentals("BBCA")


def test_an_html_challenge_page_is_reported_as_such() -> None:
    """Cloudflare serves its interstitial with a 200, so the status code says
    nothing and the body is the only signal."""
    adapter, _ = provider(FakeResponse(None, text="<!DOCTYPE html><title>Just a moment"))
    with pytest.raises(ProviderUnavailableError, match="not JSON"):
        adapter.get_fundamentals("BBCA")


def test_a_transport_failure_is_retryable() -> None:
    adapter, _ = provider(ConnectionError("connection reset"))
    with pytest.raises(ProviderUnavailableError) as exc:
        adapter.get_fundamentals("BBCA")
    assert exc.value.retryable is True


def test_a_missing_data_key_names_what_was_expected() -> None:
    """A renamed key must report itself rather than look like no coverage."""
    adapter, _ = provider({"records": []})
    with pytest.raises(ProviderUnavailableError, match="`data` key"):
        adapter.get_fundamentals("BBCA")


def test_a_null_metric_is_skipped_not_zeroed() -> None:
    """A zero would be read as a real figure - a company with no equity."""
    adapter, _ = provider({"data": [{**BBCA_ROW, "per": None, "roe": ""}]})
    parsed = metrics(adapter)
    assert "pe_ratio" not in parsed
    assert "return_on_equity" not in parsed
    assert parsed["price_to_book"] == Decimal("3.56")


# --- request pacing --------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_requests_are_paced() -> None:
    """Rate-limited without a published limit, so the pacing is ours to set."""
    clock = FakeClock()
    adapter, _ = provider(
        {"data": []}, {"data": []}, {"data": []},
        min_request_interval=1.0, clock=clock, sleep=clock.sleep,
    )
    adapter.get_fundamentals("BBCA")
    assert clock.slept == [1.0, 1.0]


# --- the price half --------------------------------------------------------


def test_quotes_are_refused_with_the_fix_named() -> None:
    """Returning an empty list would be read as "the market was closed"."""
    adapter, _ = provider()
    with pytest.raises(ProviderUnavailableError, match="composite"):
        adapter.get_quote("BBCA")


def test_price_history_is_refused_with_the_fix_named() -> None:
    adapter, _ = provider()
    with pytest.raises(ProviderUnavailableError, match="fundamentals only"):
        adapter.get_historical_candles(
            "BBCA", Timeframe.D1, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
        )


def test_realtime_is_not_claimed() -> None:
    adapter, _ = provider()
    assert adapter.supports_realtime() is False


def test_fundamentals_are_attributed_to_this_adapter() -> None:
    adapter, _ = provider()
    assert adapter.fundamentals_source_name() == "idx"
