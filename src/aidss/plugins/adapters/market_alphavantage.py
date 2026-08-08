"""Alpha Vantage adapter - the fundamentals source Yahoo stopped being.

Section 9 wants a source whose terms permit programmatic access. Yahoo's
``quoteSummary`` endpoint answers 401 now, and IDX's own JSON sits behind a
Cloudflare challenge; both were probed rather than assumed. Alpha Vantage
answered, publishes a documented contract, and issues free keys, so this is
the adapter fundamentals actually run on.

**The free tier is 25 requests per day.** That is unusable for price
collection and entirely sufficient for fundamentals, which change quarterly.
The intended deployment is therefore prices from one provider and fundamentals
from this one - see :mod:`aidss.plugins.adapters.market_composite`, which is
what makes that a configuration choice rather than a fork.

Two things about this API are worth stating before reading the code, because
both are the kind of thing that produces silent corruption rather than an
error:

  * **Every failure arrives as HTTP 200.** A bad symbol, an exhausted quota,
    and a premium-only endpoint are all 200 with a JSON body carrying
    ``Error Message``, ``Note``, or ``Information``. An adapter that checks
    the status code and parses the body is not checking anything, so the body
    is inspected first here and mapped onto the same retryable/permanent
    distinction the rest of the plugin layer uses.
  * **Numbers arrive as strings, and "missing" arrives as the string
    ``"None"``.** ``Decimal("None")`` raises, and a provider whose absent
    values crash the parser would take out every metric in the payload
    alongside the one that was missing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

#: Domain timeframe -> (function, interval). H4 has no equivalent and is
#: rejected rather than served as something adjacent.
_INTRADAY_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "60min",
}

#: Timeframe -> (function, series key). Alpha Vantage names the series key
#: differently per function and does not repeat it anywhere machine-readable,
#: so the mapping is spelled out.
_SERIES: dict[Timeframe, tuple[str, str]] = {
    Timeframe.D1: ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    Timeframe.W1: ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    Timeframe.MN1: ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}

#: OVERVIEW field -> the metric vocabulary already stored in
#: `fundamental_metrics`. Sharing the vocabulary with the Yahoo adapter is the
#: point: a `pe_ratio` row must mean the same thing whichever provider wrote
#: it, or comparing two assets collected at different times compares nothing.
_METRIC_NAMES: dict[str, str] = {
    "MarketCapitalization": "market_cap",
    "EBITDA": "ebitda",
    "PERatio": "pe_ratio",
    "ForwardPE": "forward_pe_ratio",
    "PEGRatio": "peg_ratio",
    "PriceToBookRatio": "price_to_book",
    "PriceToSalesRatioTTM": "price_to_sales",
    "EVToEBITDA": "ev_to_ebitda",
    "EVToRevenue": "ev_to_revenue",
    "ReturnOnEquityTTM": "return_on_equity",
    "ReturnOnAssetsTTM": "return_on_assets",
    "ProfitMargin": "profit_margin",
    "OperatingMarginTTM": "operating_margin",
    "RevenueTTM": "total_revenue",
    "GrossProfitTTM": "gross_profit",
    "RevenuePerShareTTM": "revenue_per_share",
    "QuarterlyRevenueGrowthYOY": "revenue_growth",
    "QuarterlyEarningsGrowthYOY": "earnings_growth",
    "DividendYield": "dividend_yield",
    "DividendPerShare": "dividend_per_share",
    "BookValue": "book_value_per_share",
    "EPS": "eps_trailing",
    "Beta": "beta",
    "SharesOutstanding": "shares_outstanding",
}

#: Deliberately not mapped, and the reasons are different for each group.
#:
#: `AnalystTargetPrice` and the `AnalystRating*` counts are other people's
#: recommendations. Storing them as fundamentals would let a third party's
#: opinion enter the evidence base as though it were a reported figure, and
#: the Fundamental Analyzer would then cite it as one. Section 14.4 wants the
#: platform's reasoning to rest on data, not on borrowed conclusions.
#:
#: `52WeekHigh`, `52WeekLow`, `50DayMovingAverage`, and `200DayMovingAverage`
#: are price statistics, and the Indicator Engine already computes them from
#: stored candles. Writing them here would create a second source of truth
#: that drifts against the first.
_EXCLUDED_BY_DESIGN: frozenset[str] = frozenset(
    {
        "AnalystTargetPrice",
        "AnalystRatingStrongBuy",
        "AnalystRatingBuy",
        "AnalystRatingHold",
        "AnalystRatingSell",
        "AnalystRatingStrongSell",
        "52WeekHigh",
        "52WeekLow",
        "50DayMovingAverage",
        "200DayMovingAverage",
    }
)

#: Alpha Vantage writes absent values as these strings rather than omitting
#: the key or sending null.
_MISSING = frozenset({"none", "-", "", "nan"})


def _decimal(value: Any) -> Decimal | None:
    """Parse Alpha Vantage's stringly-typed numbers, or None if absent."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _MISSING:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


@register
class AlphaVantageMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "alphavantage"

    BASE_URL = "https://www.alphavantage.co"

    #: The free tier refuses more than roughly one request per second, and says
    #: so only in the refusal. Spacing them here costs a second of wall clock
    #: and avoids spending an allowance on requests that come back empty.
    MIN_REQUEST_INTERVAL = 1.2

    def __init__(
        self,
        api_key: str,
        *,
        symbol_suffix: str = ".JKT",
        premium: bool = False,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        min_request_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError(
                "Alpha Vantage requires an API key (AIDSS_ALPHAVANTAGE_API_KEY); "
                "free keys are issued at https://www.alphavantage.co/support/#api-key"
            )
        self._api_key = api_key
        self._symbol_suffix = symbol_suffix
        self._premium = premium
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
            follow_redirects=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> AlphaVantageMarketDataProvider:
        if not settings.alphavantage_api_key:
            raise ValueError(
                "AIDSS_ALPHAVANTAGE_API_KEY is not set; "
                "use AIDSS_MARKET_DATA_PROVIDER=fixture for development"
            )
        return cls(
            settings.alphavantage_api_key,
            symbol_suffix=settings.alphavantage_symbol_suffix,
            premium=settings.alphavantage_premium,
        )

    # --- symbol mapping --------------------------------------------------

    def to_provider_symbol(self, ticker: str) -> str:
        """Map a stored ticker onto Alpha Vantage's namespace.

        Jakarta is ``.JKT`` here, not Yahoo's ``.JK`` - the suffixes are
        per-provider, which is exactly why it is a setting rather than a
        constant shared between adapters.
        """
        symbol = ticker.strip().upper()
        if "." in symbol or not self._symbol_suffix:
            return symbol
        return f"{symbol}{self._symbol_suffix}"

    # --- transport -------------------------------------------------------

    def _wait_for_slot(self) -> None:
        """Hold each request at least ``_interval`` after the last one.

        Not a substitute for the daily budget - that is enforced upstream, in
        the job layer, where a refusal can be turned into a deferral. This only
        stops a burst from being thrown away by the per-second limit.
        """
        if self._interval <= 0:
            return
        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < self._interval:
                self._sleep(self._interval - elapsed)
        self._last_request_at = self._clock()

    def _get(self, params: dict[str, Any]) -> dict:
        self._wait_for_slot()
        try:
            response = self._client.get(
                "/query", params={**params, "apikey": self._api_key}
            )
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        if response.status_code == 429:
            raise ProviderUnavailableError(self.name, "rate limited", retryable=True)
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {response.status_code}", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                self.name, f"client error {response.status_code}", retryable=False
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                self.name, f"response was not JSON: {response.text[:120]!r}", retryable=False
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                self.name, f"expected a JSON object, got {type(payload).__name__}", retryable=False
            )
        self._raise_for_body_error(payload)
        return payload

    def _raise_for_body_error(self, payload: dict) -> None:
        """Alpha Vantage reports failure in the body of a 200 response.

        Three distinct keys, and they mean different things operationally: a
        quota that resets tomorrow must not be treated the same as a symbol
        that does not exist, or the collector would retry forever on one and
        give up on the other.
        """
        note = payload.get("Note")
        if note:
            # "Thank you for using Alpha Vantage! Our standard API call
            # frequency is N calls per minute and M calls per day."
            raise ProviderUnavailableError(self.name, f"quota: {note}", retryable=True)

        information = payload.get("Information")
        if information:
            # Covers both the demo-key restriction and premium-only endpoints.
            # Neither improves by retrying: the key needs changing, not the
            # timing. The daily-limit message also arrives here on newer
            # accounts, so it is singled out as retryable.
            retryable = "rate limit" in information.lower() or "per day" in information.lower()
            raise ProviderUnavailableError(
                self.name, f"refused: {information}", retryable=retryable
            )

        error = payload.get("Error Message")
        if error:
            raise ProviderUnavailableError(
                self.name, f"invalid request: {error}", retryable=False
            )

    # --- MarketDataProvider contract -------------------------------------

    def get_quote(self, ticker: str) -> Quote:
        symbol = self.to_provider_symbol(ticker)
        payload = self._get({"function": "GLOBAL_QUOTE", "symbol": symbol})

        quote = payload.get("Global Quote")
        if not isinstance(quote, dict) or not quote:
            # An unknown symbol yields `{"Global Quote": {}}` with no error
            # key, so emptiness is the only signal there is.
            raise ProviderUnavailableError(
                self.name, f"no quote available for {symbol!r}", retryable=False
            )

        price = _decimal(quote.get("05. price"))
        if price is None:
            raise ProviderUnavailableError(
                self.name, f"quote for {symbol!r} carried no price", retryable=False
            )

        traded_on = quote.get("07. latest trading day")
        return Quote(
            ticker=ticker.strip().upper(),
            price=price,
            timestamp=_as_utc_date(traded_on) or datetime.now(UTC),
            previous_close=_decimal(quote.get("08. previous close")),
        )

    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start > end:
            raise ValueError("start must not be after end")

        symbol = self.to_provider_symbol(ticker)
        # `full` is a premium entitlement, and asking for it on a free key is
        # refused outright rather than downgraded - so the request would return
        # no data at all instead of less data. `compact` is the last ~100
        # points, which is why a long backfill needs a paid plan or a different
        # price provider; the composite adapter exists partly for that reason.
        output_size = "full" if self._premium else "compact"

        interval = _INTRADAY_INTERVAL.get(timeframe)
        if interval is not None:
            params = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": interval,
                "outputsize": output_size,
            }
            series_key = f"Time Series ({interval})"
        elif timeframe in _SERIES:
            function, series_key = _SERIES[timeframe]
            params = {"function": function, "symbol": symbol, "outputsize": output_size}
        else:
            supported = sorted(
                t.value for t in (*_INTRADAY_INTERVAL, *_SERIES)
            )
            raise ValueError(
                f"Timeframe {timeframe.value} is not offered by Alpha Vantage; "
                f"supported: {supported}"
            )

        payload = self._get(params)
        series = payload.get(series_key)
        if not isinstance(series, dict):
            raise ProviderUnavailableError(
                self.name,
                f"expected {series_key!r} in the response; got {sorted(payload)[:5]}",
                retryable=False,
            )

        tz = _series_timezone(payload.get("Meta Data"))
        candles = [
            candle
            for stamp, values in series.items()
            if (candle := _parse_bar(stamp, values, tz)) is not None
            and start <= candle.timestamp <= end
        ]
        # Alpha Vantage returns newest first; the contract is ascending.
        candles.sort(key=lambda c: c.timestamp)
        return candles

    # --- fundamentals ----------------------------------------------------

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        """Company overview metrics - the reason this adapter exists.

        The figures are stamped with ``LatestQuarter``, the reporting date they
        derive from, rather than with today. That distinction matters: a reader
        comparing two assets needs to know one set is three months staler than
        the other, and a today-stamp hides exactly that.

        An empty ``{}`` body means Alpha Vantage has no coverage for the
        symbol, which the contract expresses as an empty list and the collector
        reports as `unsupported` rather than as a failure. **Coverage outside
        US equities is uneven**, so this is a live possibility for an IDX
        ticker, not a theoretical branch.
        """
        symbol = self.to_provider_symbol(ticker)
        payload = self._get({"function": "OVERVIEW", "symbol": symbol})
        if not payload:
            return []

        as_of = _as_date(payload.get("LatestQuarter")) or datetime.now(UTC).date()
        points: list[FundamentalPoint] = []
        for field, metric in _METRIC_NAMES.items():
            value = _decimal(payload.get(field))
            if value is None:
                continue
            points.append(
                FundamentalPoint(metric=metric, period=as_of, value=value, period_type="ttm")
            )
        return points

    def supports_realtime(self) -> bool:
        # The free tier is end-of-day; realtime is a paid entitlement.
        return False

    def health_check(self) -> bool:
        try:
            self._get({"function": "GLOBAL_QUOTE", "symbol": "IBM"})
        except ProviderUnavailableError:
            return False
        return True


# --- parsing helpers -------------------------------------------------------


def _series_timezone(meta: Any) -> ZoneInfo:
    """The zone intraday stamps are expressed in, per the response itself.

    Alpha Vantage sends intraday timestamps as naive exchange-local time and
    names the zone only in ``Meta Data``. Assuming UTC would shift every bar by
    the exchange's offset - seven hours for IDX - which is the sort of error
    that produces a plausible-looking chart aligned to the wrong days.
    """
    name = None
    if isinstance(meta, dict):
        name = next((v for k, v in meta.items() if k.endswith("Time Zone")), None)
    if not isinstance(name, str) or not name.strip():
        return UTC  # type: ignore[return-value]
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return UTC  # type: ignore[return-value]


def _parse_bar(stamp: str, values: Any, tz: ZoneInfo) -> Candle | None:
    """One OHLCV bar, or None when the row is unusable.

    A single malformed row drops itself rather than failing the request: a gap
    in the series is recoverable and an exception loses the other several
    thousand bars that parsed fine.
    """
    if not isinstance(values, dict):
        return None

    timestamp = _parse_stamp(stamp, tz)
    if timestamp is None:
        return None

    open_ = _decimal(values.get("1. open"))
    high = _decimal(values.get("2. high"))
    low = _decimal(values.get("3. low"))
    close = _decimal(values.get("4. close"))
    if None in (open_, high, low, close):
        return None

    volume = _decimal(values.get("5. volume")) or Decimal(0)
    return Candle(
        timestamp=timestamp,
        open=open_,  # type: ignore[arg-type]
        high=high,  # type: ignore[arg-type]
        low=low,  # type: ignore[arg-type]
        close=close,  # type: ignore[arg-type]
        volume=volume,
    )


def _parse_stamp(stamp: str, tz: ZoneInfo) -> datetime | None:
    """Daily keys are ``YYYY-MM-DD``; intraday keys add a time."""
    text = str(stamp).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # A date-only key names a trading day, not an instant. Midnight UTC is
        # the convention, stated here so it is a decision rather than an
        # accident of strptime's defaults.
        zone = tz if fmt.endswith("%S") else UTC
        return parsed.replace(tzinfo=zone).astimezone(UTC)
    return None


def _as_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _as_utc_date(value: Any) -> datetime | None:
    parsed = _as_date(value)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC) if parsed else None
