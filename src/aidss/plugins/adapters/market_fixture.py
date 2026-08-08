"""A deterministic MarketDataProvider for development, CI, and demos.

Not a real data source: every candle comes from a PRNG seeded by the ticker,
so results are identical on every run. That lets Phase 2 and Phase 3 be tested
end to end without paid API calls and without depending on sources whose
licensing status is unclear (Section 9).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

from aidss.config import Settings
from aidss.domain.types import Candle, Quote, Timeframe
from aidss.plugins.interfaces import MarketDataProvider
from aidss.plugins.registry import register

_CENT = Decimal("0.01")

#: Starting price per ticker, so series for well-known issuers look plausible.
_SEED_PRICES: dict[str, float] = {
    "BBCA": 9500.0,
    "BBRI": 4700.0,
    "TLKM": 3100.0,
    "ASII": 5100.0,
    "GOTO": 68.0,
}
_DEFAULT_SEED_PRICE = 1000.0


@register
class FixtureMarketDataProvider(MarketDataProvider):
    name: ClassVar[str] = "fixture"

    def __init__(self, *, volatility: float = 0.012) -> None:
        self._volatility = volatility

    @classmethod
    def from_settings(cls, settings: Settings) -> FixtureMarketDataProvider:  # noqa: ARG003
        return cls()

    def get_quote(self, ticker: str) -> Quote:
        end = datetime.now(UTC)
        start = end - timedelta(days=5)
        candles = self.get_historical_candles(ticker, Timeframe.D1, start, end)
        if not candles:
            raise ValueError(f"No data available for ticker {ticker!r}")
        last = candles[-1]
        return Quote(
            ticker=ticker.upper(),
            price=last.close,
            timestamp=last.timestamp,
            previous_close=candles[-2].close if len(candles) > 1 else None,
            volume=last.volume,
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

        # Anchor to an absolute grid so overlapping ranges yield identical bars
        # at identical timestamps. The collector's idempotency depends on it:
        # re-fetching the same window must not shift any value.
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        first_index = -(-int((start - epoch).total_seconds()) // timeframe.seconds)
        last_index = int((end - epoch).total_seconds()) // timeframe.seconds

        candles: list[Candle] = []
        base = _SEED_PRICES.get(ticker.upper(), _DEFAULT_SEED_PRICE)
        for index in range(first_index, last_index + 1):
            rng = random.Random(f"{ticker.upper()}|{timeframe.value}|{index}")
            # Gentle drift plus noise - all of it a pure function of
            # (ticker, timeframe, index).
            drift = 1.0 + 0.00035 * ((index % 240) - 120) / 120
            noise = 1.0 + rng.uniform(-self._volatility, self._volatility)
            close = base * drift * noise
            open_ = close * (1.0 + rng.uniform(-self._volatility / 2, self._volatility / 2))
            high = max(open_, close) * (1.0 + rng.uniform(0.0, self._volatility / 2))
            low = min(open_, close) * (1.0 - rng.uniform(0.0, self._volatility / 2))
            volume = float(rng.randint(100_000, 5_000_000))
            candles.append(
                Candle(
                    timestamp=epoch + timedelta(seconds=index * timeframe.seconds),
                    open=Decimal(str(round(open_, 2))).quantize(_CENT),
                    high=Decimal(str(round(high, 2))).quantize(_CENT),
                    low=Decimal(str(round(low, 2))).quantize(_CENT),
                    close=Decimal(str(round(close, 2))).quantize(_CENT),
                    volume=Decimal(str(volume)),
                )
            )
        return candles

    def supports_realtime(self) -> bool:
        return False
