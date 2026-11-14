"""Signal to order intent (docs/05-MODULE-SPECIFICATIONS/02): sizing, quantizing, minimums.

Rules that matter more than they look:

* An entry with no stop, or with a stop at or above the entry, is refused. Without
  a stop there is nothing to size from (ADR-008).
* Quantity is rounded DOWN, so realised risk never exceeds the risk amount.
* A required risk limit that is unset refuses the intent (FR-T11). There is no
  fallback value.
* The identity of an intent is a pure function of its inputs, so evaluating the
  same candle again after a restart cannot create a second one, and the
  `clientOrderId` derived from it is the idempotency key (ADR-024).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from aidss_trader.config.limits import RiskLimits, unset_risk_fields
from aidss_trader.market_data.pairs import PairRules, check_order, floor_to_increment
from aidss_trader.strategy.base import Signal, SignalKind


@dataclass(frozen=True, slots=True)
class Intent:
    identity: str
    strategy_version: str
    pair: str
    side: str
    entry_price: Decimal
    quantity: Decimal
    stop_price: Decimal | None
    risk_amount_idr: Decimal | None
    rule_snapshot: dict[str, str]
    mode: str  # PAPER | APPROVAL | AUTO
    signal_candle_open: datetime


@dataclass(frozen=True, slots=True)
class IntentResult:
    intent: Intent | None
    reasons: list[str] = field(default_factory=list)


_EIGHT = Decimal("1e-8")


def _exact(value: Decimal | None) -> Decimal | None:
    """Undo storage noise. The exchange's finest step is 8 decimals, and SQLite (the test
    database) returns a Numeric as a float, 0.075987840000000001 for 0.07598784."""
    return None if value is None else value.quantize(_EIGHT)


def intent_from_row(row: Any, *, mode: str) -> Intent:
    """Rebuild an intent from its stored row (duck-typed: this module knows no database)."""
    return Intent(
        identity=row.identity,
        strategy_version=row.strategy_version,
        pair=row.pair,
        side=row.side,
        entry_price=_exact(row.entry_price),
        quantity=_exact(row.quantity),
        stop_price=_exact(row.stop_price),
        risk_amount_idr=_exact(row.risk_amount_idr),
        rule_snapshot=row.rule_snapshot or {},
        mode=mode,
        signal_candle_open=row.created_at,
    )


def intent_identity(strategy_version: str, pair: str, candle_open: datetime, side: str) -> str:
    return f"{strategy_version}|{pair}|{candle_open.isoformat()}|{side}"


def client_order_id(identity: str, attempt: int = 0) -> str:
    """Deterministic, `[A-Za-z0-9_-]{1,36}`. A reprice is a new order with a new attempt number."""
    digest = hashlib.sha256(f"{identity}|{attempt}".encode()).hexdigest()
    return "t" + digest[:34]


def _refuse(*reasons: str) -> IntentResult:
    return IntentResult(None, list(reasons))


def build_entry_intent(
    signal: Signal,
    *,
    strategy_version: str,
    pair: str,
    candle_open: datetime,
    equity_idr: Decimal,
    limits: RiskLimits | None,
    rules: PairRules,
    best_bid: Decimal,
    mode: str,
) -> IntentResult:
    if signal.kind is not SignalKind.ENTRY:
        return _refuse("not an entry signal")
    missing = unset_risk_fields(limits)
    if missing or limits is None:
        return _refuse(*[f"limit unset: {name}" for name in missing])
    if not rules.tradable:
        return _refuse(f"pair blocked: {', '.join(rules.blocked_reasons)}")
    assert rules.price_increment is not None and rules.quantity_increment is not None

    entry = floor_to_increment(best_bid, rules.price_increment)
    stop = signal.stop_hint
    if stop is None or stop <= 0 or stop >= entry:
        return _refuse("an entry needs a stop below the entry price")
    if equity_idr <= 0:
        return _refuse("equity is not positive")

    assert limits.risk_per_trade_pct is not None and limits.max_order_idr is not None
    assert limits.max_exposure_per_pair_pct is not None
    assert limits.max_total_exposure_pct is not None
    risk_amount = equity_idr * limits.risk_per_trade_pct / 100
    raw = risk_amount / (entry - stop)
    caps = [
        equity_idr * limits.max_exposure_per_pair_pct / 100 / entry,
        equity_idr * limits.max_total_exposure_pct / 100 / entry,
        limits.max_order_idr / entry,
    ]
    quantity = floor_to_increment(min([raw, *caps]), rules.quantity_increment)
    if quantity <= 0:
        return _refuse("quantity rounds to zero")
    problems = check_order(rules, entry, quantity)
    if problems:
        return _refuse(*problems)

    identity = intent_identity(strategy_version, pair, candle_open, "BUY")
    return IntentResult(
        Intent(
            identity=identity,
            strategy_version=strategy_version,
            pair=pair,
            side="BUY",
            entry_price=entry,
            quantity=quantity,
            stop_price=stop,
            risk_amount_idr=(entry - stop) * quantity,
            rule_snapshot=dict(signal.inputs),
            mode=mode,
            signal_candle_open=candle_open,
        )
    )


def build_exit_intent(
    signal: Signal,
    *,
    strategy_version: str,
    pair: str,
    candle_open: datetime,
    position_qty: Decimal,
    rules: PairRules,
    best_ask: Decimal,
    mode: str,
) -> IntentResult:
    """A signal exit: a LIMIT sell at the best ask. A stop exit is built elsewhere, as MARKET."""
    if signal.kind is not SignalKind.EXIT:
        return _refuse("not an exit signal")
    if not rules.tradable:
        return _refuse(f"pair blocked: {', '.join(rules.blocked_reasons)}")
    assert rules.price_increment is not None and rules.quantity_increment is not None
    price = floor_to_increment(best_ask, rules.price_increment)
    quantity = floor_to_increment(position_qty, rules.quantity_increment)
    if quantity <= 0:
        return _refuse("nothing sellable (dust below the quantity increment)")
    problems = check_order(rules, price, quantity)
    if problems:
        return _refuse(*problems)  # includes dust below the pair minimum: reported, not hidden
    return IntentResult(
        Intent(
            identity=intent_identity(strategy_version, pair, candle_open, "SELL"),
            strategy_version=strategy_version,
            pair=pair,
            side="SELL",
            entry_price=price,
            quantity=quantity,
            stop_price=None,
            risk_amount_idr=None,
            rule_snapshot=dict(signal.inputs),
            mode=mode,
            signal_candle_open=candle_open,
        )
    )
