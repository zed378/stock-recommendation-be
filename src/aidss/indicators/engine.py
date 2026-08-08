"""Indicator Engine (Phase 3, Section 7).

Runs every configured indicator over one (asset, timeframe) pair and stores the
result in ``technical_indicators``. One row per (indicator, params, timestamp),
so RSI(14) and RSI(7) coexist instead of overwriting each other.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import TechnicalIndicator
from aidss.domain.types import Candle, Timeframe
from aidss.indicators import core


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """One indicator together with its parameters."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def params_key(self) -> str:
        """A stable key for the unique constraint - sorted, so order-independent."""
        return ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))


#: The default indicator set, covering the Technical category in Section 5.3.
DEFAULT_SPECS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec("sma", {"period": 20}),
    IndicatorSpec("sma", {"period": 50}),
    IndicatorSpec("sma", {"period": 200}),
    IndicatorSpec("ema", {"period": 12}),
    IndicatorSpec("ema", {"period": 26}),
    IndicatorSpec("rsi", {"period": 14}),
    IndicatorSpec("macd", {"fast": 12, "slow": 26, "signal": 9}),
    IndicatorSpec("bollinger", {"period": 20, "num_std": 2.0}),
    IndicatorSpec("atr", {"period": 14}),
    IndicatorSpec("adx", {"period": 14}),
    IndicatorSpec("stochastic", {"k_period": 14, "d_period": 3}),
    IndicatorSpec("ichimoku", {"conversion": 9, "base": 26, "span_b": 52}),
    IndicatorSpec("obv", {}),
    IndicatorSpec("volume_ratio", {"period": 20}),
    IndicatorSpec("volatility", {"period": 20}),
)


def candles_to_frame(candles: list[Candle]) -> pd.DataFrame:
    """Convert candles to a time-indexed float DataFrame.

    Decimal is the storage type, because prices need exact precision; float is
    the computation type, because indicators are continuous-domain maths. The
    conversion happens here and nowhere else.
    """
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(
        {
            "open": [float(c.open) for c in candles],
            "high": [float(c.high) for c in candles],
            "low": [float(c.low) for c in candles],
            "close": [float(c.close) for c in candles],
            "volume": [float(c.volume) for c in candles],
        },
        index=pd.DatetimeIndex([c.timestamp for c in candles], name="timestamp"),
    )
    return frame.sort_index()


def compute(frame: pd.DataFrame, spec: IndicatorSpec) -> pd.DataFrame:
    """Compute one indicator. Always returns a DataFrame, possibly multi-column."""
    p = spec.params
    match spec.name:
        case "sma":
            return core.sma(frame["close"], p["period"]).to_frame("value")
        case "ema":
            return core.ema(frame["close"], p["period"]).to_frame("value")
        case "rsi":
            return core.rsi(frame["close"], p["period"]).to_frame("value")
        case "macd":
            return core.macd(frame["close"], p["fast"], p["slow"], p["signal"])
        case "bollinger":
            return core.bollinger_bands(frame["close"], p["period"], p["num_std"])
        case "atr":
            return core.atr(frame["high"], frame["low"], frame["close"], p["period"]).to_frame(
                "value"
            )
        case "adx":
            return core.adx(frame["high"], frame["low"], frame["close"], p["period"])
        case "stochastic":
            return core.stochastic(
                frame["high"], frame["low"], frame["close"], p["k_period"], p["d_period"]
            )
        case "ichimoku":
            return core.ichimoku(
                frame["high"], frame["low"], frame["close"],
                p["conversion"], p["base"], p["span_b"],
            )
        case "obv":
            return core.obv(frame["close"], frame["volume"]).to_frame("value")
        case "volume_ratio":
            return core.volume_ratio(frame["volume"], p["period"]).to_frame("value")
        case "volatility":
            return core.rolling_volatility(frame["close"], p["period"]).to_frame("value")
        case _:
            raise ValueError(f"Unknown indicator: {spec.name!r}")


def _clean(value: Any) -> Any:
    """NaN and inf have no JSON representation, so they are stored as null."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


@dataclass(slots=True)
class IndicatorRunReport:
    asset_id: uuid.UUID
    timeframe: Timeframe
    bars: int
    computed: dict[str, int] = field(default_factory=dict)
    inserted: int = 0
    updated: int = 0
    skipped_all_null: int = 0


class IndicatorEngine:
    def __init__(self, specs: tuple[IndicatorSpec, ...] = DEFAULT_SPECS) -> None:
        self.specs = specs

    def compute_all(self, candles: list[Candle]) -> dict[str, pd.DataFrame]:
        """Compute every spec without touching the database; the API uses this too."""
        frame = candles_to_frame(candles)
        results: dict[str, pd.DataFrame] = {}
        for spec in self.specs:
            key = f"{spec.name}({spec.params_key})" if spec.params_key else spec.name
            results[key] = compute(frame, spec)
        return results

    def snapshot(self, candles: list[Candle]) -> dict[str, Any]:
        """Latest indicator values plus market structure - ready-made AI context.

        This is the shape the Context Builder will consume in Phase 4: the
        numbers are already settled, leaving the AI only the interpretation.
        """
        frame = candles_to_frame(candles)
        if frame.empty:
            return {"bars": 0, "indicators": {}, "levels": {}, "structure": "undetermined"}

        latest: dict[str, Any] = {}
        for spec in self.specs:
            result = compute(frame, spec)
            key = f"{spec.name}({spec.params_key})" if spec.params_key else spec.name
            latest[key] = {
                column: _clean(result[column].iloc[-1]) for column in result.columns
            }

        return {
            "bars": len(frame),
            "as_of": frame.index[-1].isoformat(),
            "last_close": float(frame["close"].iloc[-1]),
            "indicators": latest,
            "levels": core.support_resistance(frame["high"], frame["low"], frame["close"]),
            "breakout": core.detect_breakout(frame["high"], frame["low"], frame["close"]),
            "structure": core.market_structure(frame["high"], frame["low"]),
        }

    def persist(
        self,
        session: Session,
        asset_id: uuid.UUID,
        timeframe: Timeframe,
        candles: list[Candle],
    ) -> IndicatorRunReport:
        frame = candles_to_frame(candles)
        report = IndicatorRunReport(asset_id=asset_id, timeframe=timeframe, bars=len(frame))
        if frame.empty:
            return report

        for spec in self.specs:
            result = compute(frame, spec)
            report.computed[spec.name] = int(result.notna().any(axis=1).sum())
            self._persist_one(session, asset_id, timeframe, spec, result, report)

        session.flush()
        return report

    def _persist_one(
        self,
        session: Session,
        asset_id: uuid.UUID,
        timeframe: Timeframe,
        spec: IndicatorSpec,
        result: pd.DataFrame,
        report: IndicatorRunReport,
    ) -> None:
        existing_rows = session.scalars(
            select(TechnicalIndicator).where(
                TechnicalIndicator.asset_id == asset_id,
                TechnicalIndicator.timeframe == timeframe.value,
                TechnicalIndicator.indicator_name == spec.name,
                TechnicalIndicator.params_key == spec.params_key,
            )
        ).all()
        existing = {row.timestamp: row for row in existing_rows}

        for timestamp, row in result.iterrows():
            payload = {column: _clean(row[column]) for column in result.columns}
            if all(v is None for v in payload.values()):
                # Warm-up period: no value yet. Storing it would fill the table
                # with rows that carry no information.
                report.skipped_all_null += 1
                continue

            timestamp = timestamp.to_pydatetime()
            current = existing.get(timestamp)
            if current is None:
                session.add(
                    TechnicalIndicator(
                        asset_id=asset_id,
                        timeframe=timeframe.value,
                        timestamp=timestamp,
                        indicator_name=spec.name,
                        params_key=spec.params_key,
                        value=payload,
                    )
                )
                report.inserted += 1
            elif current.value != payload:
                current.value = payload
                report.updated += 1
