"""Who owns a pair in the paper book, and what each strategy has earned there (S2, ADR-062).

Several strategies share one paper account, so a pair needs exactly one owner at a time: the
strategy that opened its position. A BUY intent that is still waiting for its fill *claims* the
pair, so two strategies cannot both enter on the same candle. Only the owner may sell it, by its
own exit signal or by the stop its entry set.

Everything here is derived from rows that already exist (PAPER fills, their orders, their
intents), so there is no second book to drift out of step with the ledger. The one thing the old
schema could not say, which strategy an intent came from, is the nullable
`order_intent.strategy_id`; NULL means the reference strategy.

Anything this cannot attribute raises `OwnershipError`, and the runtime then makes no new paper
entry rather than guessing an owner (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.db.models import Fill, OrderIntentRow, OrderRow
from aidss_trader.ledger.position import LedgerIntegrityError, Position, apply_fill

REFERENCE = "ema_adx"
ZERO = Decimal(0)


class OwnershipError(Exception):
    """A paper fill or intent cannot be attributed to exactly one strategy."""


@dataclass(frozen=True, slots=True)
class Trade:
    """One sale, with the strategy that owned the position it closed (or reduced)."""

    at: datetime
    pair: str
    strategy_id: str
    realised: Decimal


@dataclass(frozen=True, slots=True)
class Stats:
    trades: int = 0
    wins: int = 0
    pnl: Decimal = ZERO
    drawdown_pct: Decimal | None = None  # None with no trades: "no evidence", never zero


@dataclass(slots=True)
class Ownership:
    positions: dict[str, Position] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)  # open positions
    claims: dict[str, str] = field(default_factory=dict)  # BUY intents waiting for their fill
    conflicts: set[str] = field(default_factory=set)  # pairs claimed by more than one strategy
    trades: list[Trade] = field(default_factory=list)

    def owner_of(self, pair: str) -> str | None:
        """The strategy holding or claiming the pair, or None when it is free."""
        return self.owners.get(pair) or self.claims.get(pair)

    def blocked_for(self, pair: str, strategy_id: str) -> str | None:
        """Why `strategy_id` may not enter `pair` now, or None when it may."""
        if pair in self.conflicts:
            return "pair_ownership_conflict"
        owner = self.owner_of(pair)
        if owner is not None and owner != strategy_id:
            return f"pair_owned_by:{owner}"
        return None

    def owned_by(self, strategy_id: str) -> dict[str, Position]:
        return {p: pos for p, pos in self.positions.items() if self.owners.get(p) == strategy_id}

    def last_exit(self, strategy_id: str, pair: str) -> datetime | None:
        return next(
            (
                t.at
                for t in reversed(self.trades)
                if t.strategy_id == strategy_id and t.pair == pair
            ),
            None,
        )


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def paper_ownership(session: Session) -> Ownership:
    """Replay the PAPER fills in the ledger's own order and attribute each one."""
    intents = {
        i.identity: (i.strategy_id or REFERENCE)
        for i in session.scalars(select(OrderIntentRow).where(OrderIntentRow.origin == "PAPER"))
    }
    rows = session.execute(
        select(Fill, OrderRow.intent_identity)
        .join(OrderRow, OrderRow.id == Fill.order_id)
        .where(Fill.origin == "PAPER")
    ).all()
    # Same order as `accounting.replay_origin`, so positions agree with the ledger exactly.
    rows.sort(key=lambda r: (_aware(r[0].executed_at), r[0].side == "SELL"))

    out = Ownership()
    for fill, identity in rows:
        current = out.positions.get(fill.pair, Position())
        if fill.side == "BUY":
            if identity is None or identity not in intents:
                raise OwnershipError(f"a PAPER buy in {fill.pair} has no intent to attribute it to")
            owner = intents[identity]
            if current.quantity > 0 and out.owners.get(fill.pair) not in (None, owner):
                raise OwnershipError(f"{fill.pair} was added to by a strategy that does not own it")
            out.owners.setdefault(fill.pair, owner)
        try:
            updated, realised = apply_fill(
                current, fill.side, fill.quantity, fill.price, fill.commission
            )
        except LedgerIntegrityError as exc:
            raise OwnershipError(f"the PAPER ledger is inconsistent in {fill.pair}: {exc}") from exc
        out.positions[fill.pair] = updated
        if fill.side == "SELL":
            owner = out.owners.get(fill.pair)
            if owner is None:
                raise OwnershipError(f"a PAPER sale in {fill.pair} has no owner to attribute it to")
            out.trades.append(Trade(_aware(fill.executed_at), fill.pair, owner, realised))
            if updated.quantity == 0:
                del out.owners[fill.pair]
    out.positions = {p: pos for p, pos in out.positions.items() if pos.quantity > 0}

    pending = session.scalars(
        select(OrderIntentRow)
        .where(
            OrderIntentRow.origin == "PAPER",
            OrderIntentRow.side == "BUY",
            OrderIntentRow.state == "PAPER_RECORDED",
        )
        .order_by(OrderIntentRow.created_at)
    )
    for intent in pending:
        owner = intent.strategy_id or REFERENCE
        existing = out.claims.get(intent.pair) or out.owners.get(intent.pair)
        if existing is not None and existing != owner:
            out.conflicts.add(intent.pair)
        else:
            out.claims.setdefault(intent.pair, owner)
    return out


def strategy_stats(
    ownership: Ownership, start_equity: Decimal, *, since: datetime | None = None
) -> dict[str, Stats]:
    """Trades, wins, PnL and drawdown of each strategy's own sales.

    Drawdown is the largest peak-to-trough fall of `start_equity` plus that strategy's cumulative
    realised PnL. The account curve is shared and cannot say who earned what, so it is not used.
    Open positions are not marked to market here: this is realised evidence only.
    """
    by: dict[str, list[Trade]] = {}
    for t in ownership.trades:
        if since is None or t.at >= _aware(since):
            by.setdefault(t.strategy_id, []).append(t)
    out: dict[str, Stats] = {}
    for sid, trades in by.items():
        equity = peak = start_equity
        worst = ZERO
        for t in trades:
            equity += t.realised
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100)
        out[sid] = Stats(
            len(trades),
            sum(1 for t in trades if t.realised > 0),
            sum((t.realised for t in trades), ZERO),
            worst,
        )
    return out


def paper_entry_refusal(
    *,
    limits,
    equity: Decimal,
    open_positions: int,
    pair_exposure: Decimal,
    total_exposure: Decimal,
    value: Decimal,
) -> str | None:
    """The three portfolio limits the Risk Engine applies to a live entry, for a paper entry.

    Mirrors `risk.engine.evaluate` (`open_positions`, `pair_exposure`, `total_exposure`); a test
    holds the two in agreement. Paper has no order to send, so the rest of that profile does not
    apply, but these three decide how many strategies can hold positions at once, and a paper book
    that ignored them would show results live could never have had.
    """
    if limits.max_open_positions is None or open_positions >= limits.max_open_positions:
        return f"open_positions {open_positions} reaches the limit {limits.max_open_positions}"
    if equity <= 0:
        return "no equity to size against"
    pair_pct = (pair_exposure + value) / equity * 100
    if pair_pct > limits.max_exposure_per_pair_pct:
        return f"pair_exposure {pair_pct:.2f}% above {limits.max_exposure_per_pair_pct}%"
    total_pct = (total_exposure + value) / equity * 100
    if total_pct > limits.max_total_exposure_pct:
        return f"total_exposure {total_pct:.2f}% above {limits.max_total_exposure_pct}%"
    return None
