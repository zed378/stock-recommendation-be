"""Indodax IDR rule builder. Models are reviewed elsewhere, never in this strategy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from aidss_trader.connector.types import Candle
from aidss_trader.strategy.base import PositionState, Signal, SignalKind
from aidss_trader.strategy.indicators import atr
from aidss_trader.strategy.rules import RuleGroup, StrictModel, evaluate_group


class BuilderDefinition(StrictModel):
    exchange: Literal["INDODAX"]
    quote: Literal["IDR"]
    timeframe: Literal["4H", "1D"]
    entry: RuleGroup
    exit: RuleGroup
    atr_period: int = Field(ge=2, le=100, strict=True)
    atr_stop_multiple: Decimal = Field(gt=0, le=20)
    cooldown_s: int = Field(ge=0, strict=True)
    max_data_age_seconds: int = Field(gt=0, strict=True)
    max_review_age_seconds: int = Field(gt=0, strict=True)
    forecast_bars: int = Field(ge=1, le=30, strict=True)
    forecast_samples: int = Field(ge=1, le=10, strict=True)
    min_projected_return_pct: Decimal
    ai_min_score: int = Field(ge=0, le=100, strict=True)


@dataclass(frozen=True)
class BuilderParams:
    definition: dict[str, Any]


def candle_fingerprint(candles: Sequence[Candle]) -> str:
    data = [
        [
            c.open_time.isoformat(),
            *(format(v.normalize(), "f") for v in (c.open, c.high, c.low, c.close, c.volume)),
        ]
        for c in candles
    ]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


class DeclarativeStrategy:
    name = "signal_builder"

    def __init__(self, definition: BuilderDefinition) -> None:
        self.definition = definition
        self.params = BuilderParams(definition.model_dump(mode="json"))

    def version_id(self) -> str:
        canonical = json.dumps(self.params.definition, sort_keys=True, separators=(",", ":"))
        return f"{self.name}-{hashlib.sha256(canonical.encode()).hexdigest()[:12]}"

    def min_history(self) -> int:
        operands = [
            op
            for g in (self.definition.entry, self.definition.exit)
            for r in g.rules
            for op in (r.left, r.right)
        ]
        return max(
            20, self.definition.atr_period + 1, *(2 * (op.period or 1) + 2 for op in operands)
        )

    def evaluate(self, candles: Sequence[Candle], position: PositionState) -> Signal:
        d = self.definition
        if len(candles) < self.min_history():
            return Signal(SignalKind.NONE, "insufficient_history")
        # Bound history identically in the worker and runtime; a rolling store must
        # not invalidate a review merely by adding older candles.
        window = list(candles[-self.min_history() :])
        group = evaluate_group(d.exit if position.long else d.entry, window)
        inputs = {
            "builder_rules": json.dumps(group, sort_keys=True),
            "builder_data_hash": candle_fingerprint(window),
            "builder_timeframe": d.timeframe,
        }
        if not group["available"]:
            return Signal(SignalKind.NONE, "missing_indicator", inputs=inputs)
        if position.long:
            return Signal(
                SignalKind.EXIT if group["passed"] else SignalKind.NONE,
                "builder_exit" if group["passed"] else "hold",
                inputs=inputs,
            )
        if (
            position.last_exit_at is not None
            and (window[-1].open_time - position.last_exit_at).total_seconds() < d.cooldown_s
        ):
            return Signal(SignalKind.NONE, "cooldown", inputs=inputs)
        if not group["passed"]:
            return Signal(SignalKind.NONE, "entry_rules_not_met", inputs=inputs)
        volatility = atr(window, d.atr_period)[-1]
        stop = window[-1].close - d.atr_stop_multiple * volatility if volatility else None
        if stop is None or not 0 < stop < window[-1].close:
            return Signal(SignalKind.NONE, "invalid_stop", inputs=inputs)
        return Signal(SignalKind.ENTRY, "builder_entry", stop_hint=stop, inputs=inputs)
