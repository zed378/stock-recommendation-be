"""Score a coin with the stock-pick criteria, unchanged.

This reuses `aidss.screener` rather than copying it: the criteria, their weights and the way a
missing indicator is handled are the platform's, so a coin and a stock are judged by the same
named conditions. What is added here is only what a screen does not have: an eligibility check, a
combined score over the horizons the owner chose, and mechanical stop and target levels (the
stock picks name conditions; they never price an exit).

A coin the screen could not fully read is **not scored**: a criterion that could not be checked is
not a criterion that failed, and counting it as either would let a short history decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aidss.domain.types import Candle
from aidss.indicators.engine import IndicatorEngine
from aidss.screener.criteria import CRITERIA_BY_HORIZON, Horizon
from aidss.screener.engine import horizon_scores
from aidss_signals.config import MIN_DAILY_BARS


@dataclass(frozen=True, slots=True)
class AssetScore:
    eligible: bool
    reason: str
    horizons: tuple[str, ...]
    met: dict[str, list[str]] = field(default_factory=dict)
    failed: dict[str, list[str]] = field(default_factory=dict)
    unevaluable: dict[str, list[str]] = field(default_factory=dict)
    score: float = 0.0
    max_score: float = 0.0
    ratio: float = 0.0
    close: float | None = None
    atr: float | None = None
    numbers: dict[str, float | None] = field(default_factory=dict)


def _ind(snapshot: dict[str, Any], key: str, field_name: str = "value") -> float | None:
    node = (snapshot.get("indicators") or {}).get(key)
    if not isinstance(node, dict):
        return None
    value = node.get(field_name)
    return float(value) if isinstance(value, (int, float)) else None


def snapshot_numbers(snapshot: dict[str, Any]) -> dict[str, float | None]:
    return {
        "rsi14": _ind(snapshot, "rsi(period=14)"),
        "macd_histogram": _ind(snapshot, "macd(fast=12,signal=9,slow=26)", "histogram"),
        "adx14": _ind(snapshot, "adx(period=14)", "adx"),
        "plus_di": _ind(snapshot, "adx(period=14)", "plus_di"),
        "minus_di": _ind(snapshot, "adx(period=14)", "minus_di"),
        "sma20": _ind(snapshot, "sma(period=20)"),
        "sma50": _ind(snapshot, "sma(period=50)"),
        "sma200": _ind(snapshot, "sma(period=200)"),
        "atr14": _ind(snapshot, "atr(period=14)"),
        "volume_ratio20": _ind(snapshot, "volume_ratio(period=20)"),
    }


def score_asset(candles: list[Candle], horizons: tuple[str, ...]) -> AssetScore:
    if len(candles) < MIN_DAILY_BARS:
        return AssetScore(False, f"history_too_short:{len(candles)}<{MIN_DAILY_BARS}", horizons)
    read = horizon_scores(candles)
    if not read:
        return AssetScore(False, "no_indicator_snapshot", horizons)
    met: dict[str, list[str]] = {}
    failed: dict[str, list[str]] = {}
    unevaluable: dict[str, list[str]] = {}
    score = max_score = 0.0
    for name in horizons:
        criteria = CRITERIA_BY_HORIZON[Horizon(name)]
        node = read.get(name, {})
        fired = set(node.get("met", []))
        missing = list(node.get("unevaluable", []))
        met[name] = [c.key for c in criteria if c.key in fired]
        unevaluable[name] = missing
        failed[name] = [c.key for c in criteria if c.key not in fired and c.key not in missing]
        score += sum(c.weight for c in criteria if c.key in fired)
        max_score += sum(c.weight for c in criteria)
    snapshot = IndicatorEngine().snapshot(candles)
    numbers = snapshot_numbers(snapshot)
    close = float(candles[-1].close)
    if any(unevaluable.values()):
        return AssetScore(
            False,
            "unevaluable_criteria",
            horizons,
            met,
            failed,
            unevaluable,
            score,
            max_score,
            score / max_score if max_score else 0.0,
            close,
            numbers.get("atr14"),
            numbers,
        )
    return AssetScore(
        True,
        "ok",
        horizons,
        met,
        failed,
        unevaluable,
        score,
        max_score,
        score / max_score if max_score else 0.0,
        close,
        numbers.get("atr14"),
        numbers,
    )


def btc_bias(candles: list[Candle]) -> str:
    """The client's BTC filter reads "bullish" or "bearish": above its 50-bar average with the 50
    above the 200 is bullish, anything measured otherwise is bearish, and no reading is ''."""
    if len(candles) < MIN_DAILY_BARS:
        return ""
    snapshot = IndicatorEngine().snapshot(candles)
    n = snapshot_numbers(snapshot)
    close = float(candles[-1].close)
    if n["sma50"] is None or n["sma200"] is None:
        return ""
    return "bullish" if close > n["sma50"] and n["sma50"] > n["sma200"] else "bearish"


def mechanical_levels(
    close: float, atr: float | None, stop_multiple: float, tp_r: tuple[float, float, float]
) -> dict[str, float] | None:
    """Stop at a multiple of ATR below the close and targets at multiples of that distance. None
    when it cannot be priced sensibly (no ATR, or a stop at or below zero)."""
    if atr is None or atr <= 0 or close <= 0:
        return None
    stop = close - stop_multiple * atr
    if stop <= 0:
        return None
    risk = close - stop
    px = lambda v: float(f"{v:.10g}")  # noqa: E731
    return {
        "entry": px(close),
        "stop": px(stop),
        "tp1": px(close + tp_r[0] * risk),
        "tp2": px(close + tp_r[1] * risk),
        "tp3": px(close + tp_r[2] * risk),
        "stop_distance_pct": round(risk / close * 100, 2),
    }
