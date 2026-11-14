from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aidss_trader.connector.types import Candle
from aidss_trader.strategy import EmaAdxParams, EmaAdxStrategy, PositionState, SignalKind
from aidss_trader.strategy.indicators import adx, atr, ema

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)

# Test parameters live here, in the test. They are not the owner's choices and are not defaults.
PARAMS = EmaAdxParams(
    ema_fast=3,
    ema_slow=6,
    adx_period=3,
    adx_threshold=D("30"),
    atr_period=3,
    atr_stop_multiple=D("2"),
    cooldown_s=3600 * 8,
)


def series(closes: list[int], spread: int = 2) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        out.append(
            Candle(T0 + timedelta(hours=4 * i), D(c), D(c + spread), D(c - spread), D(c), D(1))
        )
    return out


UP = series([100 + 3 * i for i in range(40)])
DOWN = series([200 - 3 * i for i in range(40)])
FLAT = series([100, 101] * 20)


def test_ema_is_none_until_seeded_and_converges_on_a_constant() -> None:
    out = ema([D(5)] * 10, 4)
    assert out[:3] == [None] * 3 and out[3] == D(5) and out[-1] == D(5)


def test_atr_and_adx_have_no_value_without_enough_history() -> None:
    short = series([100, 101, 102])
    assert atr(short, 3)[-1] is None and adx(short, 3)[-1] is None
    assert atr(UP, 3)[-1] is not None and adx(UP, 3)[-1] is not None


def test_adx_is_high_in_a_strong_trend_and_low_in_a_flat_market() -> None:
    assert adx(UP, 3)[-1] > D("40")
    # a period of 3 is very jumpy; the point is only that a trend reads far higher
    assert adx(FLAT, 3)[-1] < D("30")


def test_strategy_is_deterministic() -> None:
    s = EmaAdxStrategy(PARAMS)
    a, b = s.evaluate(UP, PositionState()), s.evaluate(UP, PositionState())
    assert a == b and repr(a) == repr(b)


def test_entry_in_a_strong_uptrend_with_a_stop_below_the_close() -> None:
    sig = EmaAdxStrategy(PARAMS).evaluate(UP, PositionState())
    assert sig.kind is SignalKind.ENTRY and sig.stop_hint < UP[-1].close
    assert "ema_fast" in sig.inputs and "adx" in sig.inputs


def test_no_entry_in_a_flat_market_or_a_downtrend() -> None:
    s = EmaAdxStrategy(PARAMS)
    assert s.evaluate(FLAT, PositionState()).kind is SignalKind.NONE
    assert s.evaluate(DOWN, PositionState()).kind is SignalKind.NONE


def test_exit_when_the_trend_filter_fails_while_long() -> None:
    sig = EmaAdxStrategy(PARAMS).evaluate(DOWN, PositionState(long=True, entry_price=D(150)))
    assert sig.kind is SignalKind.EXIT


def test_hold_while_the_trend_continues() -> None:
    assert EmaAdxStrategy(PARAMS).evaluate(UP, PositionState(long=True)).kind is SignalKind.NONE


def test_insufficient_history_is_none_with_a_reason() -> None:
    sig = EmaAdxStrategy(PARAMS).evaluate(UP[:4], PositionState())
    assert (sig.kind, sig.reason) == (SignalKind.NONE, "insufficient_history")


def test_cooldown_after_an_exit_blocks_a_fresh_entry() -> None:
    s = EmaAdxStrategy(PARAMS)
    recent = PositionState(last_exit_at=UP[-1].open_time - timedelta(hours=4))
    assert s.evaluate(UP, recent).reason == "cooldown"
    old = PositionState(last_exit_at=UP[-1].open_time - timedelta(days=5))
    assert s.evaluate(UP, old).kind is SignalKind.ENTRY


def test_a_parameter_change_is_a_new_version() -> None:
    other = EmaAdxParams(3, 6, 3, D("25"), 3, D("2"), 3600)
    assert EmaAdxStrategy(PARAMS).version_id() != EmaAdxStrategy(other).version_id()
    assert EmaAdxStrategy(PARAMS).version_id() == EmaAdxStrategy(PARAMS).version_id()


def test_parameters_have_no_defaults_and_are_validated() -> None:
    with pytest.raises(TypeError):
        EmaAdxParams()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        EmaAdxParams(6, 3, 3, D(20), 3, D(2), 0)


def test_the_strategy_package_imports_nothing_from_the_trader_outside_itself() -> None:
    """The strategy cannot reach the connector's client, the database, or the order path."""
    root = Path(__file__).resolve().parents[2] / "src" / "aidss_trader" / "strategy"
    allowed = ("aidss_trader.strategy", "aidss_trader.connector.types")
    bad = []
    files = list(root.glob("*.py"))
    assert files
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            bad += [m for m in mods if m.startswith("aidss_trader") and not m.startswith(allowed)]
    assert not bad, bad
