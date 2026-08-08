"""Yahoo Finance market data via the public chart endpoint.

**Status: unofficial, and chosen deliberately.** Section 9 of the planning
document marks this source grey: there is no published contract, Yahoo's terms
restrict automated commercial use, and nothing about the endpoint is
guaranteed. The project owner has accepted that trade-off in exchange for a
free, key-less source with real IDX coverage.

What that acceptance means for this code is concrete, not rhetorical:

  * **It will break without notice.** The endpoint is undocumented, so the
    parser validates the response shape rather than trusting it, and reports a
    clear error instead of a KeyError when the shape changes.
  * **It will rate-limit without telling you the limit.** 429 is mapped to a
    retryable failure so the collector backs off rather than hammering.
  * **It is not the source of record.** Nothing here is more authoritative than
    IDX itself. If this platform ever needs data it can stand behind, an
    official or licensed feed replaces this adapter - which is a one-line
    configuration change, by design.

Coverage note: Indonesian tickers carry a ``.JK`` suffix on Yahoo (BBCA ->
BBCA.JK). The suffix is applied automatically to any ticker that does not
already contain one, and is configurable for other markets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

#: Domain timeframe -> Yahoo interval. There is no 4-hour interval, so H4 is
#: rejected outright rather than silently served as something else.
_INTERVAL: dict[Timeframe, str] = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "1h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MN1: "1mo",
}

#: Yahoo caps how far back each intraday interval reaches. Requesting more
#: returns fewer bars than asked for rather than an error, so the limits are
#: recorded here to make a short result explainable instead of mysterious.
MAX_HISTORY_DAYS: dict[Timeframe, int] = {
    Timeframe.M1: 7,
    Timeframe.M5: 60,
    Timeframe.M15: 60,
    Timeframe.M30: 60,
    Timeframe.H1: 730,
}

#: A browser-like User-Agent. The default httpx agent is refused outright, so
#: this is required for the request to work at all rather than an attempt to
#: disguise the client.
_USER_AGENT = "Mozilla/5.0 (compatible; aidss/0.1; +https://github.com/)"

#: quoteSummary modules queried for fundamentals. Ordered by precedence: when a
#: metric appears in more than one, the earlier module wins.
_FUNDAMENTAL_MODULES: tuple[str, ...] = (
    "defaultKeyStatistics",
    "financialData",
    "summaryDetail",
)

#: Yahoo's field names mapped onto the vocabulary stored in
#: `fundamental_metrics`. Only fields with a stable, unambiguous meaning are
#: mapped - a metric whose definition varies between providers would produce
#: comparisons that look valid and are not.
_METRIC_NAMES: dict[str, str] = {
    "trailingPE": "pe_ratio",
    "forwardPE": "forward_pe_ratio",
    "priceToBook": "price_to_book",
    "enterpriseToEbitda": "ev_to_ebitda",
    "enterpriseToRevenue": "ev_to_revenue",
    "returnOnEquity": "return_on_equity",
    "returnOnAssets": "return_on_assets",
    "profitMargins": "profit_margin",
    "operatingMargins": "operating_margin",
    "grossMargins": "gross_margin",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "quickRatio": "quick_ratio",
    "revenueGrowth": "revenue_growth",
    "earningsGrowth": "earnings_growth",
    "totalRevenue": "total_revenue",
    "totalDebt": "total_debt",
    "totalCash": "total_cash",
    "freeCashflow": "free_cash_flow",
    "operatingCashflow": "operating_cash_flow",
    "ebitda": "ebitda",
    "dividendYield": "dividend_yield",
    "payoutRatio": "payout_ratio",
    "beta": "beta",
    "marketCap": "market_cap",
    "bookValue": "book_value_per_share",
    "trailingEps": "eps_trailing",
    "forwardEps": "eps_forward",
}


def _raw_number(field: Any) -> Decimal | None:
    """Pull the numeric value out of Yahoo's ``{"raw": ..., "fmt": ...}`` wrapper.

    The ``fmt`` string is deliberately ignored: parsing "1.23B" back into a
    number is locale-dependent and every implementation gets some locale wrong.
    """
    if field is None:
        return None
    if isinstance(field, (int, float)):
        return Decimal(str(field))
    if isinstance(field, dict):
        raw = field.get("raw")
        if isinstance(raw, (int, float)):
            return Decimal(str(raw))
    return None


@register
class YahooMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "yahoo"

    BASE_URL = "https://query1.finance.yahoo.com"

    def __init__(
        self,
        *,
        symbol_suffix: str = ".JK",
        client: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._symbol_suffix = symbol_suffix
        self._client = client or httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> YahooMarketDataProvider:
        return cls(symbol_suffix=settings.yahoo_symbol_suffix)

    # --- symbol mapping --------------------------------------------------

    def to_yahoo_symbol(self, ticker: str) -> str:
        """Map a stored ticker onto Yahoo's symbol namespace.

        A ticker that already carries a market suffix is passed through
        untouched, so a non-IDX asset can be registered with its explicit
        Yahoo symbol (``AAPL`` with an empty suffix, ``BMW.DE``, and so on)
        without the IDX default being forced onto it.
        """
        symbol = ticker.strip().upper()
        if "." in symbol or not self._symbol_suffix:
            return symbol
        return f"{symbol}{self._symbol_suffix}"

    # --- transport -------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        try:
            response = self._client.get(path, params=params)
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        if response.status_code == 429:
            # Yahoo publishes no limit, so the only sane response is to back
            # off and try later.
            raise ProviderUnavailableError(
                self.name, "rate limited (no published limit; back off)", retryable=True
            )
        if response.status_code in (401, 403):
            raise ProviderUnavailableError(
                self.name,
                f"access refused ({response.status_code}) - the unofficial endpoint may "
                "have changed its access rules",
                retryable=False,
            )
        if response.status_code == 404:
            raise ProviderUnavailableError(
                self.name, "symbol not found", retryable=False
            )
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {response.status_code}", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                self.name, f"client error {response.status_code}", retryable=False
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                self.name, f"response was not JSON: {response.text[:120]!r}", retryable=False
            ) from exc

    def _chart_result(self, payload: dict) -> dict:
        """Pull the single result out of a chart response, shape-checked.

        The endpoint is undocumented, so its shape is verified rather than
        assumed. A changed schema then reports itself instead of surfacing as
        a KeyError three layers up.
        """
        chart = payload.get("chart")
        if not isinstance(chart, dict):
            raise ProviderUnavailableError(
                self.name, f"unexpected response shape: {list(payload)[:5]}", retryable=False
            )

        error = chart.get("error")
        if error:
            description = error.get("description") if isinstance(error, dict) else str(error)
            raise ProviderUnavailableError(
                self.name, f"upstream error: {description}", retryable=False
            )

        results = chart.get("result")
        if not results:
            raise ProviderUnavailableError(self.name, "no result in response", retryable=False)
        return results[0]

    # --- MarketDataProvider contract -------------------------------------

    def get_quote(self, ticker: str) -> Quote:
        symbol = self.to_yahoo_symbol(ticker)
        payload = self._get(
            f"/v8/finance/chart/{symbol}", {"interval": "1d", "range": "5d"}
        )
        meta = self._chart_result(payload).get("meta") or {}

        price = meta.get("regularMarketPrice")
        if price is None:
            raise ProviderUnavailableError(
                self.name, f"no quote available for {symbol!r}", retryable=False
            )

        timestamp = meta.get("regularMarketTime")
        return Quote(
            ticker=ticker.strip().upper(),
            price=_to_decimal(price),
            timestamp=(
                datetime.fromtimestamp(int(timestamp), tz=UTC)
                if timestamp
                else datetime.now(UTC)
            ),
            previous_close=(
                _to_decimal(meta["chartPreviousClose"])
                if meta.get("chartPreviousClose") is not None
                else None
            ),
        )

    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        interval = _INTERVAL.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Timeframe {timeframe.value} is not offered by Yahoo Finance; "
                f"supported: {sorted(t.value for t in _INTERVAL)}"
            )
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start > end:
            raise ValueError("start must not be after end")

        symbol = self.to_yahoo_symbol(ticker)
        payload = self._get(
            f"/v8/finance/chart/{symbol}",
            {
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "interval": interval,
                "includePrePost": "false",
            },
        )
        return self._parse_candles(self._chart_result(payload))

    def _parse_candles(self, result: dict) -> list[Candle]:
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quotes = indicators.get("quote") or [{}]
        quote = quotes[0] if quotes else {}

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        candles: list[Candle] = []
        for i, ts in enumerate(timestamps):
            values = (
                _at(opens, i),
                _at(highs, i),
                _at(lows, i),
                _at(closes, i),
            )
            # Yahoo emits nulls for halted or non-trading slots. Dropping them
            # here keeps a gap out of the series rather than letting a
            # zero-filled bar reach the Indicator Engine and distort an average.
            if any(v is None for v in values) or ts is None:
                continue

            try:
                open_, high, low, close = (_to_decimal(v) for v in values)
                volume = _to_decimal(_at(volumes, i) or 0)
            except (InvalidOperation, TypeError, ValueError):
                continue

            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(int(ts), tz=UTC),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )
        return candles

    # --- fundamentals ----------------------------------------------------

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        """Key statistics and trailing financials from the quoteSummary endpoint.

        Yahoo returns each figure as ``{"raw": ..., "fmt": ...}``; the raw value
        is used and the formatted one ignored, because "1.23B" would have to be
        parsed back into a number and every locale gets that wrong differently.

        These are point-in-time statistics, not a filing history. They are
        stamped with today's date and marked ``ttm``, which is what they are -
        labelling them as a quarterly period would let a reader line them up
        against actual quarters they do not correspond to.

        **Known limitation.** Yahoo now answers this endpoint with 401 for
        unauthenticated callers, unlike the chart endpoint used for prices.
        The parser is complete and tested against a recorded payload, but in
        practice this method currently raises a non-retryable
        ``ProviderUnavailableError``. Working around the 401 is deliberately
        not implemented: using an undocumented but open endpoint is one thing,
        defeating an access control the provider added is another. Fundamentals
        need a provider that permits programmatic access.
        """
        symbol = self.to_yahoo_symbol(ticker)
        payload = self._get(
            f"/v10/finance/quoteSummary/{symbol}",
            {"modules": ",".join(_FUNDAMENTAL_MODULES)},
        )

        summary = payload.get("quoteSummary")
        if not isinstance(summary, dict):
            raise ProviderUnavailableError(
                self.name, f"unexpected quoteSummary shape: {list(payload)[:5]}", retryable=False
            )
        if summary.get("error"):
            raise ProviderUnavailableError(
                self.name, f"upstream error: {summary['error']}", retryable=False
            )
        results = summary.get("result")
        if not results:
            return []

        block = results[0]
        as_of = datetime.now(UTC).date()
        points: list[FundamentalPoint] = []

        for module in _FUNDAMENTAL_MODULES:
            section = block.get(module)
            if not isinstance(section, dict):
                continue
            for key, mapped in _METRIC_NAMES.items():
                value = _raw_number(section.get(key))
                if value is None:
                    continue
                points.append(
                    FundamentalPoint(
                        metric=mapped, period=as_of, value=value, period_type="ttm"
                    )
                )

        # Deduplicated because a metric can appear in more than one module; the
        # first occurrence wins so the module order above decides precedence.
        seen: set[str] = set()
        unique: list[FundamentalPoint] = []
        for point in points:
            if point.metric in seen:
                continue
            seen.add(point.metric)
            unique.append(point)
        return unique

    def supports_realtime(self) -> bool:
        # The public endpoint is delayed - typically around 15 minutes for
        # equities. Claiming realtime here would mislead every caller that
        # checks (Section 9).
        return False

    def health_check(self) -> bool:
        try:
            self._get("/v8/finance/chart/BBCA.JK", {"interval": "1d", "range": "5d"})
        except ProviderUnavailableError:
            return False
        return True


def _at(values: list, index: int) -> Any:
    return values[index] if index < len(values) else None


def _to_decimal(value: Any) -> Decimal:
    """Convert via str so a float's binary representation is not carried in."""
    return Decimal(str(value))
