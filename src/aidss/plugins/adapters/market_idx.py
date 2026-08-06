"""IDX fundamentals, from the exchange's own public statistics API.

**This adapter impersonates a browser, and that was a decision rather than an
oversight.** The endpoint sits behind Cloudflare, which refuses an ordinary
HTTP client; ``curl_cffi`` presents a browser's TLS fingerprint so the request
is accepted. The project owner chose this route with the alternatives on the
table, after the others were tried and found closed:

  * Yahoo's ``quoteSummary`` answers 401 - an authentication requirement, and
    working around one is a different thing from this.
  * Alpha Vantage was tested against a real key and publishes **nothing** for
    IDX symbols: ``BBCA.JKT``, ``BBCA.JK``, and ``BBRI.JKT`` all return ``{}``.
  * The endpoint older scrapers used, ``umbraco/Surface/ListedCompany/
    GetTradingInfoSS``, is gone - 404, not 403.

What the choice does and does not involve is worth stating plainly, because
"unofficial" covers several different things. There is no account here, no
credential, and no paywall: IDX publishes these figures for the investing
public, free and without a login. What is being got past is bot management,
not access control. What it does *not* clear is IDX's terms, which prohibit
redistributing this data to third parties commercially - so this is sound for
personal research and is a question to revisit before the platform is used
more widely (Section 13).

Practical consequences, all of which the code takes seriously: it can break
without notice, so the response shape is verified rather than trusted; it is
rate-limited without publishing a limit, so requests are paced; and it is not
a source this platform can stand behind commercially.

Two properties of the payload matter more than anything else here, because
both are silent hundred-fold errors rather than parse failures:

  * **Money is in billions of rupiah.** BBCA's assets arrive as
    ``1433701.78``, meaning Rp 1,434 trillion. Stored raw, next to Alpha
    Vantage's absolute figures, the two differ by a factor of a billion.
  * **`roa`, `roe`, and `npm` are percentages**, where every other provider
    here reports fractions. IDX says ``20.82`` and Alpha Vantage says
    ``0.345`` for the same concept.

Neither is documented; both were established by checking issuers across three
orders of magnitude. Every conversion below is therefore explicit and
individually justified, and a test pins the cross-provider agreement.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from aidss.config import Settings
from aidss.domain.types import Candle, FundamentalPoint, Quote, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

BASE_URL = "https://www.idx.co.id/primary"

#: Sent because the API expects to be called from its own page. Not a
#: disguise - the request genuinely originates from this application - but
#: omitting it gets the request refused.
RATIO_REFERER = (
    "https://www.idx.co.id/id/data-pasar/laporan-statistik/digital-statistic/monthly/"
    "financial-report-and-ratio-of-listed-companies/financial-data-and-ratio"
)

#: How many past years to look back through when the current one has no filing
#: yet. Bounded: without a limit, a delisted ticker would walk back forever.
MAX_YEARS_BACK = 3


def _billions(value: Decimal) -> Decimal:
    """Rupiah, from IDX's billions.

    Established by comparison, not documentation: Adaro's assets arrive as
    165,208.73 against a known ~Rp 165 trillion, and a micro-cap's as 4.06
    against ~Rp 4 billion. Three orders of magnitude apart, same scale.
    """
    return value * Decimal("1e9")


def _percent(value: Decimal) -> Decimal:
    """A fraction, from IDX's percentage points.

    Adaro's ROE arrives as 19.7421. As a percentage that is right; as a
    fraction it would be 1,974%. Alpha Vantage reports the same concept as
    0.345, so storing IDX's number unconverted would put values a hundred-fold
    apart in one column - and every threshold rule downstream reads that column
    without asking which provider filled it.
    """
    return value / Decimal(100)


#: IDX field -> (stored metric name, conversion). The metric names are the same
#: vocabulary the Yahoo and Alpha Vantage adapters use; a cross-provider test
#: pins that, because two adapters can each be right alone and still write rows
#: that cannot be compared.
_METRICS: dict[str, tuple[str, Callable[[Decimal], Decimal] | None]] = {
    # Ratios, already unitless.
    "per": ("pe_ratio", None),
    "priceBV": ("price_to_book", None),
    "deRatio": ("debt_to_equity", None),
    # Percentages in the payload, fractions in the column. Both are annualised
    # by IDX - BBCA's 3.72% ROA reconciles against nine months of profit scaled
    # to twelve, not against the nine months as reported - which is what makes
    # them comparable to another provider's trailing-twelve-month figure.
    "roa": ("return_on_assets", _percent),
    "roe": ("return_on_equity", _percent),
    # Per-share figures, already in rupiah.
    "eps": ("eps_trailing", None),
    "bookValue": ("book_value_per_share", None),
    # Billions of rupiah in the payload, rupiah in the column.
    "assets": ("total_assets", _billions),
    "liabilities": ("total_liabilities", _billions),
    "equity": ("total_equity", _billions),
    "sales": ("total_revenue", _billions),
    "ebt": ("earnings_before_tax", _billions),
    "profitAttrOwner": ("net_income", _billions),
}

#: Deliberately not mapped, for two different reasons.
#:
#: `profitPeriod` is profit including minority interests, where
#: `profitAttrOwner` excludes them. The two differ by a fraction of a percent
#: for most issuers and by a great deal for a few, and storing both under
#: near-identical names invites whichever one a reader happens to pick.
#:
#: `npm` is not the margin the rest of the system means by `profit_margin`.
#: For BBCA it reports 74.1% while `profitAttrOwner / sales` from the very
#: same row is 56.3%, so IDX derives it from a different denominator - net
#: interest income rather than gross, most likely, for a bank. Alpha Vantage's
#: `ProfitMargin` *is* net income over revenue. Filing two different
#: calculations under one name would produce comparisons that look valid and
#: are not. Both inputs are stored, so a consistent margin can be derived
#: wherever it is needed.
_EXCLUDED_BY_DESIGN = frozenset({"profitPeriod", "npm"})

#: Month numbers for the fiscal year ends IDX reports.
_FISCAL_MONTHS: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _as_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


@register
class IDXMarketDataProvider(MarketDataProvider):
    """Fundamentals only. Prices come from elsewhere - see the composite adapter."""

    name: ClassVar[str] = "idx"

    #: The API rate-limits without publishing a limit, so requests are spaced.
    #: One second matches what the endpoint tolerates in practice.
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        timeout: float = 30.0,
        session: Any | None = None,
        min_request_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._impersonate = impersonate
        self._timeout = timeout
        self._session = session
        self._interval = (
            self.MIN_REQUEST_INTERVAL if min_request_interval is None else min_request_interval
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> IDXMarketDataProvider:
        return cls(impersonate=settings.idx_impersonate)

    # --- transport -------------------------------------------------------

    def _client(self) -> Any:
        """Built lazily so importing this module needs no `curl_cffi`.

        The dependency is only required when the adapter is actually selected,
        and the error says what to install rather than surfacing as an
        ImportError during plugin registration.
        """
        if self._session is not None:
            return self._session
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise ProviderUnavailableError(
                self.name,
                "curl_cffi is required for the IDX adapter (pip install curl_cffi); "
                "an ordinary HTTP client is refused by the endpoint",
                retryable=False,
            ) from exc
        self._session = curl_requests.Session(
            impersonate=self._impersonate, timeout=self._timeout
        )
        return self._session

    def _wait_for_slot(self) -> None:
        if self._interval <= 0:
            return
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            if elapsed < self._interval:
                self._sleep(self._interval - elapsed)
        self._last_request_at = self._clock()

    def _get(self, path: str, params: dict[str, Any], *, referer: str) -> Any:
        self._wait_for_slot()
        try:
            response = self._client().get(
                f"{BASE_URL}{path}",
                params=params,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
                    "Referer": referer,
                },
            )
        except Exception as exc:  # noqa: BLE001 - curl_cffi raises its own hierarchy
            raise ProviderUnavailableError(
                self.name, f"request failed: {type(exc).__name__}: {exc}", retryable=True
            ) from exc

        status = response.status_code
        if status == 429:
            raise ProviderUnavailableError(
                self.name, "rate limited (no published limit; back off)", retryable=True
            )
        if status in (401, 403):
            # The most likely single cause of this adapter breaking: the
            # protection was tightened past what impersonation clears. Say so,
            # rather than reporting it as an ordinary client error.
            raise ProviderUnavailableError(
                self.name,
                f"refused ({status}) - the endpoint's bot protection no longer accepts "
                "this client; the impersonation profile may need updating, or the route "
                "may have closed",
                retryable=False,
            )
        if status == 404:
            raise ProviderUnavailableError(
                self.name, f"endpoint {path} no longer exists", retryable=False
            )
        if status >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {status}", retryable=True
            )
        if status >= 400:
            raise ProviderUnavailableError(
                self.name, f"client error {status}", retryable=False
            )

        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            body = response.text[:160] if hasattr(response, "text") else ""
            # A Cloudflare challenge page is HTML with a 200, so this branch is
            # the one that catches "we were quietly served the interstitial".
            raise ProviderUnavailableError(
                self.name, f"response was not JSON: {body!r}", retryable=False
            ) from exc

    # --- the listed-company directory ------------------------------------

    def list_companies(self) -> list[dict[str, Any]]:
        """Every company listed on IDX, as the exchange itself publishes them.

        One request: the endpoint returns all ~962 in a single page, so paging
        would be ceremony around a list that fits comfortably in memory. The
        length is asked for generously and the total is checked against what
        came back, because a silently truncated directory is a directory that
        quietly stops recognising the companies past the cut.

        Only equity issuers. The same endpoint also carries bond, ETF and EBA
        listings, which have codes that are not tickers and would tag news to
        instruments nobody analyses.
        """
        payload = self._get(
            "/ListedCompany/GetCompanyProfiles",
            {"start": 0, "length": 2000, "sortColumn": "Code", "sortOrder": "asc"},
            referer="https://www.idx.co.id/id/perusahaan-tercatat/profil-perusahaan-tercatat/",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ProviderUnavailableError(
                self.name,
                f"company directory had an unexpected shape: {type(payload).__name__}",
                retryable=False,
            )

        rows = payload["data"]
        total = payload.get("recordsTotal")
        if isinstance(total, int) and len(rows) < total:
            raise ProviderUnavailableError(
                self.name,
                f"directory truncated: {len(rows)} of {total} returned. Raise the page "
                "length rather than importing a partial directory, which would silently "
                "stop recognising every issuer past the cut",
                retryable=True,
            )
        return [row for row in rows if isinstance(row, dict) and row.get("EfekEmiten_Saham")]

    # --- fundamentals ----------------------------------------------------

    def get_fundamentals(self, ticker: str) -> list[FundamentalPoint]:
        """Reported financials and ratios for one issuer.

        Walks back through recent years until a filing is found, because the
        current year has no data until the first quarter is published, and an
        empty result then would read as "IDX does not cover this issuer".
        """
        code = ticker.strip().upper()
        today = datetime.now(UTC).date()

        for offset in range(MAX_YEARS_BACK):
            year = today.year - offset
            row = self._find_row(code, year)
            if row is not None:
                return self._parse(row, year)
        return []

    def _find_row(self, code: str, year: int) -> dict | None:
        payload = self._get(
            "/DigitalStatistic/GetApiDataPaginated",
            {
                "urlName": "LINK_FINANCIAL_DATA_RATIO",
                "periodQuarter": 4,
                "periodYear": year,
                "type": "yearly",
                "isPrint": "false",
                "cumulative": "false",
                "pageSize": 50,
                "orderBy": "",
                "search": code,
                "pageNumber": 1,
            },
            referer=RATIO_REFERER,
        )

        if not isinstance(payload, dict):
            raise ProviderUnavailableError(
                self.name,
                f"expected a JSON object, got {type(payload).__name__}",
                retryable=False,
            )
        rows = payload.get("data")
        if rows is None:
            raise ProviderUnavailableError(
                self.name,
                f"no `data` key in the response; got {sorted(payload)[:6]}",
                retryable=False,
            )
        if not isinstance(rows, list):
            raise ProviderUnavailableError(
                self.name, "`data` was not a list", retryable=False
            )

        # Matched exactly rather than trusting `search`, which is a substring
        # filter: querying BBCA also returns BBCAP, and a near-miss ticker is
        # the worst possible thing to file under the right one.
        for row in rows:
            if isinstance(row, dict) and str(row.get("code", "")).strip().upper() == code:
                return row
        return None

    def _parse(self, row: dict, year: int) -> list[FundamentalPoint]:
        reported_on = _as_date(row.get("fsDate"))
        if reported_on is None:
            raise ProviderUnavailableError(
                self.name,
                f"row for {row.get('code')!r} carried no usable fsDate ({row.get('fsDate')!r})",
                retryable=False,
            )

        period = self._fiscal_year_end(year, row.get("fiscalYearEnd"))
        basis = "annual" if reported_on >= period else "ytd"
        points: list[FundamentalPoint] = []
        for field, (metric, convert) in _METRICS.items():
            value = _decimal(row.get(field))
            if value is None:
                continue
            points.append(
                FundamentalPoint(
                    metric=metric,
                    period=period,
                    value=convert(value) if convert else value,
                    period_type=basis,
                )
            )
        return points

    def _fiscal_year_end(self, year: int, fiscal_year_end: Any) -> date:
        """The close of the fiscal year these figures belong to.

        Used as the stored ``period`` in preference to ``fsDate``, which is not
        what it sounds like: for fiscal 2024 IDX returns ``2024-09-30`` - a
        period end - and for fiscal 2025 it returns ``2025-10-20``, which is a
        filing date. Keying on it would make every refetch look like a new
        period instead of a revision of the same one, and the collector's
        upsert would accumulate near-duplicate rows rather than replacing a
        restated figure.

        The fiscal year is stable, so the row is stable. How much of that year
        the figures cover is what ``period_type`` is for.
        """
        month = _FISCAL_MONTHS.get(str(fiscal_year_end or "").strip().lower()[:3]) or 12
        # The last day of that month, without a calendar dependency: step into
        # the next month and back off by one day.
        following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return date.fromordinal(following.toordinal() - 1)

    # --- the price half of the contract ----------------------------------
    #
    # This adapter has no prices. Rather than return empty lists - which every
    # caller would read as "the market was closed" - both methods refuse, and
    # name the configuration that fixes it.

    def _no_prices(self, what: str) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            self.name,
            f"the IDX adapter serves fundamentals only and has no {what}. "
            "Use AIDSS_MARKET_DATA_PROVIDER=composite with "
            "AIDSS_COMPOSITE_PRICE_PROVIDER=yahoo and "
            "AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=idx",
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
        try:
            self._find_row("BBCA", datetime.now(UTC).date().year)
        except ProviderUnavailableError:
            return False
        return True
