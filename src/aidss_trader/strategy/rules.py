"""Declarative Decimal rules shared by Trader strategies and external reviewers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidss_trader.connector.types import Candle as RuleCandle
from aidss_trader.strategy.indicators import adx, ema, rsi, sma


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Operand(StrictModel):
    indicator: Literal["constant", "close", "ema", "rsi", "adx", "volume_ratio"]
    period: int | None = Field(default=None, ge=2, le=1000, strict=True)
    value: Decimal | None = None

    @model_validator(mode="after")
    def shape(self) -> Operand:
        if self.indicator == "constant":
            if self.value is None or self.period is not None:
                raise ValueError("constant needs value and no period")
        elif self.value is not None:
            raise ValueError("only a constant accepts value")
        elif self.indicator == "close":
            if self.period is not None:
                raise ValueError("close accepts no period")
        elif self.period is None:
            raise ValueError("indicator needs period")
        return self


class Rule(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_ -]+$")
    left: Operand
    operator: Literal["gt", "gte", "lt", "lte", "crosses_above", "crosses_below"]
    right: Operand


class RuleGroup(StrictModel):
    mode: Literal["ALL", "ANY"]
    rules: tuple[Rule, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_names(self) -> RuleGroup:
        if len({r.name for r in self.rules}) != len(self.rules):
            raise ValueError("rule names must be unique within a group")
        return self


def _series(op: Operand, candles: list[RuleCandle]) -> list[Decimal | None]:
    closes = [c.close for c in candles]
    if op.indicator == "constant":
        return [op.value] * len(candles)
    if op.indicator == "close":
        return closes
    assert op.period is not None
    if op.indicator == "ema":
        return ema(closes, op.period)
    if op.indicator == "rsi":
        return rsi(closes, op.period)
    if op.indicator == "adx":
        return adx(candles, op.period)
    # Compare current volume with previous bars, excluding the current bar.
    volumes = [c.volume for c in candles]
    averages = sma(volumes, op.period)
    return [None] + [
        v / avg if avg is not None and avg > 0 else None
        for v, avg in zip(volumes[1:], averages[:-1], strict=True)
    ]


def evaluate_group(group: RuleGroup, candles: list[RuleCandle]) -> dict[str, Any]:
    evidence = []
    for rule in group.rules:
        left, right = _series(rule.left, candles), _series(rule.right, candles)
        a, b = left[-1], right[-1]
        cross = rule.operator.startswith("crosses_")
        available = a is not None and b is not None
        available = available and (not cross or (left[-2] is not None and right[-2] is not None))
        passed = None
        if available:
            assert a is not None and b is not None
            if rule.operator == "crosses_above":
                passed = left[-2] <= right[-2] and a > b
            elif rule.operator == "crosses_below":
                passed = left[-2] >= right[-2] and a < b
            else:
                passed = {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[rule.operator]
        evidence.append(
            {
                "name": rule.name,
                "passed": passed,
                "operator": rule.operator,
                "left": str(a) if a is not None else None,
                "right": str(b) if b is not None else None,
                "previous_left": str(left[-2]) if left[-2] is not None else None,
                "previous_right": str(right[-2]) if right[-2] is not None else None,
            }
        )
    available = all(e["passed"] is not None for e in evidence)
    combine = all if group.mode == "ALL" else any
    return {
        "available": available,
        "passed": available and combine(e["passed"] for e in evidence),
        "mode": group.mode,
        "rules": evidence,
    }
