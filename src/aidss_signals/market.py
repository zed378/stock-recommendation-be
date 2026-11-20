"""Public Binance spot data, read only: 24h tickers to choose and filter coins, and closed daily
candles. No key, no signature, no account. Closed candles only: the one still forming would change
under the screen before it was done."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from aidss.domain.types import Candle

STABLE_BASES = frozenset(
    {
        "USDC",
        "FDUSD",
        "TUSD",
        "BUSD",
        "DAI",
        "USDP",
        "USDE",
        "EUR",
        "EURI",
        "AEUR",
        "GBP",
        "TRY",
        "USD1",
        "PAXG",
        "XUSD",
    }
)
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


class MarketDataError(Exception):
    pass


def _base(symbol: str) -> str:
    return symbol[: -len("USDT")]


def is_plain_coin(symbol: str) -> bool:
    """A USDT pair for a coin: not a stablecoin, a fiat pair, or a leveraged token."""
    if not symbol.endswith("USDT"):
        return False
    base = _base(symbol)
    if not base or base in STABLE_BASES or base == "USDT":
        return False
    return not any(len(base) > len(s) + 1 and base.endswith(s) for s in LEVERAGED_SUFFIXES)


class MarketData:
    def __init__(
        self,
        base: str,
        client: httpx.Client | None = None,
        *,
        spacing_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base = base
        self._client = client or httpx.Client(timeout=15.0, headers={"Accept": "application/json"})
        self._spacing = spacing_s
        self._sleep = sleep

    def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        self._sleep(self._spacing)
        try:
            res = self._client.get(f"{self._base}{path}", params=params)
        except httpx.HTTPError as exc:
            raise MarketDataError(f"{path} request failed: {type(exc).__name__}") from None
        if res.status_code != 200:
            raise MarketDataError(f"{path} answered {res.status_code}")
        try:
            return res.json()
        except ValueError:
            raise MarketDataError(f"{path} did not return JSON") from None

    def quote_volumes(self) -> dict[str, Decimal]:
        """24h quote volume in USDT for every plain USDT coin pair, from one request."""
        body = self._get("/api/v3/ticker/24hr")
        if not isinstance(body, list):
            raise MarketDataError("ticker/24hr: expected a list")
        out: dict[str, Decimal] = {}
        for row in body:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if not isinstance(symbol, str) or not is_plain_coin(symbol):
                continue
            try:
                volume = Decimal(str(row.get("quoteVolume")))
            except InvalidOperation:
                continue
            if volume.is_finite() and volume >= 0:
                out[symbol] = volume
        return out

    def daily_candles(self, symbol: str, now: datetime, limit: int = 400) -> list[Candle]:
        return self.candles(symbol, "1d", now, limit)

    def candles(self, symbol: str, interval: str, now: datetime, limit: int) -> list[Candle]:
        """Closed candles only, oldest first; a bad row fails the whole fetch."""
        body = self._get(
            "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": str(limit)}
        )
        if not isinstance(body, list):
            raise MarketDataError(f"klines {symbol}: expected a list")
        now_ms = int(now.timestamp() * 1000)
        out: list[Candle] = []
        for row in body:
            if not isinstance(row, list) or len(row) < 7:
                raise MarketDataError(f"klines {symbol}: bad row")
            try:
                open_ms, close_ms = int(row[0]), int(row[6])
                o, h, low, c, v = (Decimal(str(x)) for x in row[1:6])
            except (ValueError, InvalidOperation):
                raise MarketDataError(f"klines {symbol}: non-numeric value") from None
            if not all(x.is_finite() for x in (o, h, low, c, v)) or h < low or low <= 0:
                raise MarketDataError(f"klines {symbol}: impossible candle")
            if close_ms >= now_ms:
                continue  # still forming
            out.append(Candle(datetime.fromtimestamp(open_ms / 1000, UTC), o, h, low, c, v))
        out.sort(key=lambda x: x.timestamp)
        for a, b in zip(out, out[1:], strict=False):
            if a.timestamp == b.timestamp:
                raise MarketDataError(f"klines {symbol}: duplicate candle")
        return out
