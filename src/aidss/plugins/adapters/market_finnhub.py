"""Finnhub adapter (Section 9 - official, documented, clear rate limits).

Chosen as the first "real" adapter precisely because it has an official API
and terms of service that permit programmatic use, unlike the unofficial Yahoo
Finance endpoints or scraping TradingView/Investing.com, both of which
Section 9 rules out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import httpx

from aidss.config import Settings
from aidss.domain.types import Candle, Quote, Timeframe
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

#: Domain timeframe -> Finnhub resolution parameter.
_RESOLUTION: dict[Timeframe, str] = {
    Timeframe.M1: "1",
    Timeframe.M5: "5",
    Timeframe.M15: "15",
    Timeframe.M30: "30",
    Timeframe.H1: "60",
    Timeframe.D1: "D",
    Timeframe.W1: "W",
    Timeframe.MN1: "M",
}


@register
class FinnhubMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "finnhub"

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None, timeout: float = 10.0):
        if not api_key:
            raise ValueError("Finnhub requires an API key (AIDSS_FINNHUB_API_KEY)")
        self._api_key = api_key
        self._client = client or httpx.Client(base_url=self.BASE_URL, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> FinnhubMarketDataProvider:
        if not settings.finnhub_api_key:
            raise ValueError(
                "AIDSS_FINNHUB_API_KEY is not set; "
                "use AIDSS_MARKET_DATA_PROVIDER=fixture for development"
            )
        return cls(settings.finnhub_api_key)

    # --- internals ------------------------------------------------------

    def _get(self, path: str, params: dict[str, object]) -> dict:
        try:
            response = self._client.get(path, params={**params, "token": self._api_key})
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(
                self.name, f"request failed: {exc}", retryable=True
            ) from exc

        # The retryable flag is what lets the caller distinguish "try again"
        # from "this will never work" (Section 12.8).
        if response.status_code == 429:
            raise ProviderUnavailableError(self.name, "rate limit exceeded", retryable=True)
        if response.status_code >= 500:
            raise ProviderUnavailableError(
                self.name, f"server error {response.status_code}", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                self.name, f"client error {response.status_code}", retryable=False
            )
        return response.json()

    # --- MarketDataProvider contract ------------------------------------

    def get_quote(self, ticker: str) -> Quote:
        payload = self._get("/quote", {"symbol": ticker.upper()})
        if payload.get("c") in (None, 0):
            raise ProviderUnavailableError(
                self.name, f"no quote available for {ticker!r}", retryable=False
            )
        return Quote(
            ticker=ticker.upper(),
            price=Decimal(str(payload["c"])),
            timestamp=datetime.fromtimestamp(int(payload["t"]), tz=UTC),
            previous_close=Decimal(str(payload["pc"])) if payload.get("pc") else None,
        )

    def get_historical_candles(
        self,
        ticker: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        resolution = _RESOLUTION.get(timeframe)
        if resolution is None:
            raise ValueError(f"Timeframe {timeframe} is not supported by Finnhub")

        payload = self._get(
            "/stock/candle",
            {
                "symbol": ticker.upper(),
                "resolution": resolution,
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
            },
        )
        if payload.get("s") != "ok":
            return []

        return [
            Candle(
                timestamp=datetime.fromtimestamp(int(ts), tz=UTC),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(low)),
                close=Decimal(str(c)),
                volume=Decimal(str(v)),
            )
            for ts, o, h, low, c, v in zip(
                payload["t"], payload["o"], payload["h"], payload["l"],
                payload["c"], payload["v"], strict=True,
            )
        ]

    def supports_realtime(self) -> bool:
        return True

    def health_check(self) -> bool:
        try:
            self._get("/quote", {"symbol": "AAPL"})
        except ProviderUnavailableError:
            return False
        return True
