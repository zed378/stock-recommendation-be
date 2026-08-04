"""Feature Engineering (Phase 3, Section 6.2).

Statistical derivations that are not classical technical indicators:
multi-horizon returns, volatility, drawdown, and position within the range.
These are the supporting figures the Context Builder will hand to the AI layer
alongside the indicators themselves.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import FeatureSnapshot
from aidss.domain.types import Candle, Timeframe
from aidss.indicators.engine import candles_to_frame

#: Return horizons, measured in bars.
RETURN_HORIZONS: tuple[int, ...] = (1, 5, 20, 60)


def _finite(value: float) -> float | None:
    return None if (math.isnan(value) or math.isinf(value)) else float(value)


def compute_features(candles: list[Candle]) -> dict[str, Any]:
    """Compute features at the latest bar.

    A feature without enough history is ``None``, never 0: zero would read as a
    measured value of nothing, which is a different claim entirely.
    """
    frame = candles_to_frame(candles)
    if frame.empty:
        return {"bars": 0}

    close = frame["close"]
    features: dict[str, Any] = {"bars": len(frame)}

    for horizon in RETURN_HORIZONS:
        key = f"return_{horizon}b"
        if len(close) > horizon and close.iloc[-(horizon + 1)] != 0:
            past = close.iloc[-(horizon + 1)]
            features[key] = _finite(float(close.iloc[-1] / past - 1.0))
        else:
            features[key] = None

    log_returns = np.log(close / close.shift(1)).dropna()
    for window in (20, 60):
        key = f"volatility_{window}b"
        if len(log_returns) >= window:
            features[key] = _finite(float(log_returns.iloc[-window:].std(ddof=1) * math.sqrt(252)))
        else:
            features[key] = None

    # Running drawdown measured from the highest peak seen so far.
    running_max = close.cummax()
    drawdown = close / running_max - 1.0
    features["drawdown_current"] = _finite(float(drawdown.iloc[-1]))
    features["drawdown_max"] = _finite(float(drawdown.min()))

    # Where the close sits inside the 52-bar range: 0 is the floor, 1 the ceiling.
    window = min(52, len(frame))
    high_window = float(frame["high"].iloc[-window:].max())
    low_window = float(frame["low"].iloc[-window:].min())
    span = high_window - low_window
    features["range_position_52b"] = (
        _finite((float(close.iloc[-1]) - low_window) / span) if span > 0 else None
    )

    features["volume_mean_20b"] = (
        _finite(float(frame["volume"].iloc[-20:].mean())) if len(frame) >= 20 else None
    )
    features["gap_from_sma20"] = _gap_from_sma(close, 20)
    features["gap_from_sma50"] = _gap_from_sma(close, 50)
    return features


def _gap_from_sma(close: pd.Series, period: int) -> float | None:
    if len(close) < period:
        return None
    average = float(close.iloc[-period:].mean())
    if average == 0:
        return None
    return _finite(float(close.iloc[-1]) / average - 1.0)


def persist_features(
    session: Session,
    asset_id: uuid.UUID,
    timeframe: Timeframe,
    candles: list[Candle],
) -> FeatureSnapshot | None:
    """Upsert a feature snapshot at the latest bar's timestamp."""
    if not candles:
        return None

    features = compute_features(candles)
    timestamp = candles[-1].timestamp

    snapshot = session.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.asset_id == asset_id,
            FeatureSnapshot.timeframe == timeframe.value,
            FeatureSnapshot.timestamp == timestamp,
        )
    )
    if snapshot is None:
        snapshot = FeatureSnapshot(
            asset_id=asset_id,
            timeframe=timeframe.value,
            timestamp=timestamp,
            features=features,
        )
        session.add(snapshot)
    else:
        snapshot.features = features
    session.flush()
    return snapshot
