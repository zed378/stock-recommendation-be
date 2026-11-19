"""The rule shapes the strategy builder offers, and how a set of parameters becomes a strategy.

A user-built strategy is one of these kinds plus its parameters: data, never code. The builder
cannot run anything the code below does not already define, and a strategy built here is still a
pure function of closed candles whose signal carries no size and no authority (ADR-004, ADR-009).

Nothing is defaulted. `suggested` values are shown beside a field as a starting point the owner may
copy; a strategy is only ever built from values the owner actually submitted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from aidss_trader.strategy.base import Strategy
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy
from aidss_trader.strategy.library import (
    BollingerParams,
    BollingerReversion,
    DonchianBreakout,
    DonchianParams,
    MacdTrend,
    MacdTrendParams,
    RsiParams,
    RsiReversion,
)
from aidss_trader.strategy.variants import (
    AtrFilterParams,
    DiAtrParams,
    DiParams,
    DiRisingParams,
    EmaAdxAtrFilter,
    EmaAdxDi,
    EmaAdxDiAtrFilter,
    EmaAdxDiRising,
    EmaAdxRegime,
    EmaAdxRising,
    EmaAdxTrail,
    RegimeParams,
    RisingParams,
    TrailParams,
)

#: A strategy id is lowercase letters, digits and underscores, so it can be told apart from the
#: hash in a version id (`<id>-<hash>`).
ID_PATTERN = r"^[a-z][a-z0-9_]{1,31}$"
MAX_LABEL = 60


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: str  # "int" or "decimal"
    minimum: str
    maximum: str
    suggested: str


@dataclass(frozen=True, slots=True)
class KindSpec:
    kind: str
    family: str  # trend | mean_reversion | momentum
    fields: tuple[Field, ...]
    build: Callable[[dict[str, int | Decimal]], Strategy]


def _int(name: str, lo: int, hi: int, suggested: int) -> Field:
    return Field(name, "int", str(lo), str(hi), str(suggested))


def _dec(name: str, lo: str, hi: str, suggested: str) -> Field:
    return Field(name, "decimal", lo, hi, suggested)


_ATR = (
    _int("atr_period", 2, 100, 14),
    _dec("atr_stop_multiple", "0.1", "20", "2.5"),
    _int("cooldown_s", 0, 604800, 14400),
)

KINDS: dict[str, KindSpec] = {
    "ema_adx": KindSpec(
        "ema_adx",
        "trend",
        (
            _int("ema_fast", 2, 200, 20),
            _int("ema_slow", 3, 300, 50),
            _int("adx_period", 2, 50, 14),
            _dec("adx_threshold", "1", "100", "25"),
            *_ATR,
        ),
        lambda v: EmaAdxStrategy(EmaAdxParams(**v)),  # type: ignore[arg-type]
    ),
    "donchian_breakout": KindSpec(
        "donchian_breakout",
        "trend",
        (_int("entry_period", 2, 250, 20), _int("exit_period", 2, 250, 10), *_ATR),
        lambda v: DonchianBreakout(DonchianParams(**v)),  # type: ignore[arg-type]
    ),
    "rsi_reversion": KindSpec(
        "rsi_reversion",
        "mean_reversion",
        (
            _int("rsi_period", 2, 100, 14),
            _dec("oversold", "1", "99", "30"),
            _dec("exit_level", "1", "99", "55"),
            *_ATR,
        ),
        lambda v: RsiReversion(RsiParams(**v)),  # type: ignore[arg-type]
    ),
    "bollinger_reversion": KindSpec(
        "bollinger_reversion",
        "mean_reversion",
        (_int("period", 3, 250, 20), _dec("width", "0.1", "10", "2"), *_ATR),
        lambda v: BollingerReversion(BollingerParams(**v)),  # type: ignore[arg-type]
    ),
    "macd_trend": KindSpec(
        "macd_trend",
        "momentum",
        (
            _int("fast", 2, 100, 12),
            _int("slow", 3, 200, 26),
            _int("signal", 1, 100, 9),
            _int("trend_period", 3, 300, 100),
            *_ATR,
        ),
        lambda v: MacdTrend(MacdTrendParams(**v)),  # type: ignore[arg-type]
    ),
}


_EMA = KINDS["ema_adx"].fields

KINDS.update(
    {
        "ema_adx_rising": KindSpec(
            "ema_adx_rising",
            "trend",
            (*_EMA, _int("rise_bars", 1, 20, 3)),
            lambda v: EmaAdxRising(RisingParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_di": KindSpec(
            "ema_adx_di",
            "trend",
            (*_EMA, _dec("di_margin", "0", "99", "0")),
            lambda v: EmaAdxDi(DiParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_di_rising": KindSpec(
            "ema_adx_di_rising",
            "trend",
            (*_EMA, _dec("di_margin", "0", "99", "0"), _int("rise_bars", 1, 20, 3)),
            lambda v: EmaAdxDiRising(DiRisingParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_di_atr_filter": KindSpec(
            "ema_adx_di_atr_filter",
            "trend",
            (*_EMA, _dec("di_margin", "0", "99", "0"), _dec("min_atr_pct", "0.01", "50", "0.5")),
            lambda v: EmaAdxDiAtrFilter(DiAtrParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_atr_filter": KindSpec(
            "ema_adx_atr_filter",
            "trend",
            (*_EMA, _dec("min_atr_pct", "0.01", "50", "0.5")),
            lambda v: EmaAdxAtrFilter(AtrFilterParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_trail": KindSpec(
            "ema_adx_trail",
            "trend",
            (*_EMA, _dec("trail_atr_multiple", "0.1", "20", "3")),
            lambda v: EmaAdxTrail(TrailParams(**v)),  # type: ignore[arg-type]
        ),
        "ema_adx_regime": KindSpec(
            "ema_adx_regime",
            "trend",
            (*_EMA, _int("er_period", 2, 100, 10), _dec("er_min", "0.01", "1", "0.3")),
            lambda v: EmaAdxRegime(RegimeParams(**v)),  # type: ignore[arg-type]
        ),
    }
)


class ParameterError(ValueError):
    """A parameter the builder cannot accept; the message names the field."""


def _parse(field: Field, raw: object) -> int | Decimal:
    text = str(raw).strip()
    try:
        value: int | Decimal = int(text) if field.kind == "int" else Decimal(text)
    except (ValueError, InvalidOperation):
        what = "a whole number" if field.kind == "int" else "a number"
        raise ParameterError(f"{field.name} must be {what}") from None
    if isinstance(value, Decimal) and not value.is_finite():
        raise ParameterError(f"{field.name} must be a number")
    if value < Decimal(field.minimum) or value > Decimal(field.maximum):
        raise ParameterError(f"{field.name} must be between {field.minimum} and {field.maximum}")
    return value


def build_strategy(kind: str, params: Mapping[str, object]) -> Strategy:
    """The strategy for `kind` and exactly its parameters. Unknown kinds, missing or extra
    fields, out-of-range values and rules the rule itself rejects all raise `ParameterError`."""
    spec = KINDS.get(kind)
    if spec is None:
        raise ParameterError(f"unknown kind {kind!r}")
    names = {f.name for f in spec.fields}
    extra = sorted(set(params) - names)
    if extra:
        raise ParameterError(f"unknown parameter {extra[0]!r} for {kind}")
    missing = [f.name for f in spec.fields if params.get(f.name) in (None, "")]
    if missing:
        raise ParameterError(f"{missing[0]} is required: a strategy has no default numbers")
    values = {f.name: _parse(f, params[f.name]) for f in spec.fields}
    try:
        return spec.build(values)
    except ValueError as exc:  # the rule's own validation (for example fast must be below slow)
        raise ParameterError(str(exc)) from None
