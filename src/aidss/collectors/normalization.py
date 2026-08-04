"""Normalization - the second stage of the data pipeline (Section 6.2).

Aligns timezone, decimal precision, and duplicate handling across providers, so
a stored row no longer carries the idiosyncrasies of wherever it came from.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from aidss.domain.types import Candle, Timeframe

PRICE_QUANT = Decimal("0.00000001")
VOLUME_QUANT = Decimal("0.0001")

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


def normalize_ticker(ticker: str) -> str:
    """Basic symbol mapping: strip whitespace, upper-case, validate the shape.

    Some providers append an exchange suffix (``BBCA.JK``). The suffix is kept
    here; mapping it onto ``assets.exchange`` is each adapter's job.
    """
    cleaned = ticker.strip().upper()
    if not _TICKER_RE.match(cleaned):
        raise ValueError(f"Invalid ticker: {ticker!r}")
    return cleaned


def _quantize(value: Decimal, quant: Decimal) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_EVEN)


def normalize_candles(candles: list[Candle], timeframe: Timeframe) -> list[Candle]:
    """Sort ascending, convert to UTC, unify precision, and drop duplicates.

    When two bars share a timestamp the **later** one from the provider wins:
    providers commonly send a revision after the initial print, and the
    revision is the more accurate figure.
    """
    if not candles:
        return []

    by_slot: dict[int, Candle] = {}
    for candle in candles:
        ts = candle.timestamp.astimezone(UTC)
        # Snap to the timeframe grid so a provider whose bars are a few seconds
        # off does not create a separate row in historical_prices.
        epoch_seconds = int(ts.timestamp())
        slot = epoch_seconds - (epoch_seconds % timeframe.seconds)
        by_slot[slot] = Candle(
            timestamp=datetime.fromtimestamp(slot, tz=UTC),
            open=_quantize(candle.open, PRICE_QUANT),
            high=_quantize(candle.high, PRICE_QUANT),
            low=_quantize(candle.low, PRICE_QUANT),
            close=_quantize(candle.close, PRICE_QUANT),
            volume=_quantize(candle.volume, VOLUME_QUANT),
        )

    return [by_slot[slot] for slot in sorted(by_slot)]
