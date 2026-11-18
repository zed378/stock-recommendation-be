"""EODHD adapter: licensed fundamentals for IDX-listed companies, through a documented API.

Why this exists. IDX's own site is the fundamentals source the platform started with, and it
sits behind bot management that refuses the VM's datacenter address. Working around that is not
a fix, so the fundamentals half moves to a vendor that sells an API for exactly this: a keyed,
documented endpoint with a published contract. The owner chose EODHD on 2026-11-18.

What it serves: **fundamentals only**, for the composite provider
(`AIDSS_MARKET_DATA_PROVIDER=composite`, `AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd`, prices
still from Yahoo). Like the IDX adapter it has no quotes or candles, and says so.

Facts taken from EODHD's fundamentals page (read 2026-11-18) and **not yet observed against a
live key**: the ticker is `CODE.EXCHANGE` (`BBCA.JK`), the token travels as the `api_token` query
parameter (no header form is documented), the response is one JSON object with `General`,
`Highlights`, `Valuation`, `SharesStats`, `Technicals` and `Financials`, and a fundamentals
request costs 10 of the plan's daily API calls. The page does not document the answer for an
unknown ticker or a bad token, so those are handled by status code and treated cautiously. The
first real call may show a field name or status this did not expect; that is what the live test
(`tests/test_eodhd_live.py`, skipped without a key) is for.

The token is in the URL, so every message built here has it removed first.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

#: (section, field) -> the metric vocabulary already stored in `fundamental_metrics`. Sharing it
#: with the other adapters is the point: a `pe_ratio` row must mean the same whichever provider
#: wrote it.
_METRICS: dict[tuple[str, str], str] = {
    ("Highlights", "MarketCapitalization"): "market_cap",
    ("Highlights", "EBITDA"): "ebitda",
    ("Highlights", "PERatio"): "pe_ratio",
    ("Highlights", "PEGRatio"): "peg_ratio",
    ("Highlights", "BookValue"): "book_value_per_share",
    ("Highlights", "DividendShare"): "dividend_per_share",
    ("Highlights", "DividendYield"): "dividend_yield",
    ("Highlights", "EarningsShare"): "eps_trailing",
    ("Highlights", "ProfitMargin"): "profit_margin",
    ("Highlights", "OperatingMarginTTM"): "operating_margin",
    ("Highlights", "ReturnOnAssetsTTM"): "return_on_assets",
    ("Highlights", "ReturnOnEquityTTM"): "return_on_equity",
    ("Highlights", "RevenueTTM"): "total_revenue",
    ("Highlights", "RevenuePerShareTTM"): "revenue_per_share",
    ("Highlights", "GrossProfitTTM"): "gross_profit",
    ("Highlights", "QuarterlyRevenueGrowthYOY"): "revenue_growth",
    ("Highlights", "QuarterlyEarningsGrowthYOY"): "earnings_growth",
    ("Valuation", "ForwardPE"): "forward_pe_ratio",
    ("Valuation", "PriceBookMRQ"): "price_to_book",
    ("Valuation", "PriceSalesTTM"): "price_to_sales",
    ("Valuation", "EnterpriseValueEbitda"): "ev_to_ebitda",
    ("Valuation", "EnterpriseValueRevenue"): "ev_to_revenue",
    ("SharesStats", "SharesOutstanding"): "shares_outstanding",
    ("Technicals", "Beta"): "beta",
}

#: Deliberately not mapped. `WallStreetTargetPrice` is other people's opinion and must not enter
#: the evidence base as a reported figure; the 52-week and moving-average fields are price
#: statistics the Indicator Engine already computes from stored candles, so storing them here
#: would create a second source of truth.
_EXCLUDED_BY_DESIGN = frozenset(
    {
        ("Highlights", "WallStreetTargetPrice"),
        ("Technicals", "52WeekHigh"),
        ("Technicals", "52WeekLow"),
        ("Technicals", "50DayMA"),
        ("Technicals", "200DayMA"),
    }
)

_MISSING = frozenset({"none", "-", "", "nan", "null"})


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.lower() in _MISSING:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _as_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


@register
class EODHDMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "eodhd"

    BASE_URL = "https://eodhd.com"
    FUNDAMENTALS_PATH = "/api/v1.1/fundamentals/{symbol}"
    ACCOUNT_PATH = "/api/user"

    #: Spacing, not a budget: the daily allowance is enforced upstream
    #: (`AIDSS_FUNDAMENTALS_DAILY_QUOTA`, which the owner sets from the plan; one request here
    #: costs 10 of EODHD's calls).
    MIN_REQUEST_INTERVAL = 0.25

    def __init__(
        self,
        api_key: str,
        *,
        symbol_suffix: str = ".JK",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        min_request_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("EODHD requires an API key (AIDSS_EODHD_API_KEY)")
        self._api_key = api_key
        self._symbol_suffix = symbol_suffix
        self._interval = (
            self.MIN_REQUEST_INTERVAL if min_request_interval is None else min_request_interval
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._client = client or httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> EODHDMarketDataProvider:
        if not settings.eodhd_api_key:
            raise ValueError(
                "AIDSS_EODHD_API_KEY is not set; use AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=idx "
                "or another adapter until a key is configured"
            )
        return cls(settings.eodhd_api_key, symbol_suffix=settings.eodhd_symbol_suffix)

    # --- symbol and transport ------------------------------------------------

    def to_provider_symbol(self, ticker: str) -> str:
        symbol = ticker.strip().upper()
        if "." in symbol or not self._symbol_suffix:
            return symbol
        return f"{symbol}{self._symbol_suffix}"

    def _clean(self, text: str) -> str:
        """The token rides in the URL, so an error that quotes the URL would repeat it."""
        return text.replace(self._api_key, "<token>")

    def _wait_for_slot(self) -> None:
        if self._interval <= 0:
            return
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            if elapsed < self._interval:
                self._sleep(self._interval - elapsed)
        self._last_request_at = self._clock()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        """The decoded JSON body, or None for HTTP 404 (no such symbol)."""
        self._wait_for_slot()
        try:
            response = self._client.get(
                path, params={**(params or {}), "api_token": self._api_key, "fmt": "json"}
            )
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name,
                f"request failed: {type(exc).__name__}: {self._clean(str(exc))}",
                retryable=True,
            ) from exc

        status = response.status_code
        if status == 404:
            return None
        if status == 429:
            raise ProviderUnavailableError(self.name, "rate limited", retryable=True)
        if status == 402:
            # EODHD answers 402 when the daily allowance is used up. It resets, so waiting works.
            raise ProviderUnavailableError(
                self.name, "daily API allowance used up (402)", retryable=True
            )
        if status in (401, 403):
            raise ProviderUnavailableError(
                self.name,
                f"refused ({status}): the token is wrong, revoked, or the plan does not include "
                "this endpoint. Retrying will not help",
                retryable=False,
            )
        if status >= 500:
            raise ProviderUnavailableError(self.name, f"server error {status}", retryable=True)
        if status >= 400:
            raise ProviderUnavailableError(self.name, f"client error {status}", retryable=False)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                self.name, "response was not JSON", retryable=False
            ) from exc

    # --- MarketDataProvider contract -------------------------------------------

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        """Reported metrics, stamped with the most recent reported quarter, not with today.

        A reader comparing two companies needs to know one set is a quarter staler than the
        other, and a today-stamp would hide exactly that. An unknown symbol (404) or an empty
        body is "no coverage", which the contract expresses as an empty list.
        """
        symbol = self.to_provider_symbol(ticker)
        payload = self._get(self.FUNDAMENTALS_PATH.format(symbol=symbol))
        if payload is None or payload == {}:
            return []
        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                self.name,
                f"expected a JSON object, got {type(payload).__name__}",
                retryable=False,
            )
        general = payload.get("General")
        currency = general.get("CurrencyCode") if isinstance(general, dict) else None
        if currency and str(currency).upper() != "IDR":
            # Money fields are stored in the reporting currency. Mixing units silently is the
            # failure this guards against, so a different currency is refused, not converted.
            raise ProviderUnavailableError(
                self.name,
                f"{symbol} reports in {currency}, not IDR; refused rather than mixed",
                retryable=False,
            )
        highlights = payload.get("Highlights")
        as_of = (
            _as_date(highlights.get("MostRecentQuarter"))
            if isinstance(highlights, dict)
            else None
        ) or datetime.now(UTC).date()

        points: list[FundamentalPoint] = []
        for (section, field), metric in _METRICS.items():
            block = payload.get(section)
            if not isinstance(block, dict):
                continue
            value = _decimal(block.get(field))
            if value is None:
                continue
            points.append(
                FundamentalPoint(metric=metric, period=as_of, value=value, period_type="ttm")
            )
        return points

    def _no_prices(self, what: str) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            self.name,
            f"the EODHD adapter serves fundamentals only and has no {what}. "
            "Use AIDSS_MARKET_DATA_PROVIDER=composite with "
            "AIDSS_COMPOSITE_PRICE_PROVIDER=yahoo and "
            "AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd",
            retryable=False,
        )

    def get_quote(self, ticker: str) -> Quote:
        raise self._no_prices("quotes")

    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        raise self._no_prices("price history")

    def supports_realtime(self) -> bool:
        return False

    def health_check(self) -> bool:
        """Asks the account endpoint. That it spends no allowance and answers 200 for a valid
        token is an assumption from EODHD's naming, not something read or observed."""
        try:
            return self._get(self.ACCOUNT_PATH) is not None
        except ProviderUnavailableError:
            return False
