"""Pair rules: what the exchange says about a pair, and what blocks trading it.

A missing or contradictory rule blocks the pair; it is never defaulted
(docs/06-INTEGRATIONS/05). Rounding is always *down*: rounding a quantity up
could exceed the risk the order was sized for or the balance that funds it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from sqlalchemy.orm import Session

from aidss_trader.connector.types import PairInfo
from aidss_trader.db.models import PairRule


@dataclass(frozen=True, slots=True)
class PairRules:
    pair: str
    ticker_id: str
    quantity_increment: Decimal | None
    price_increment: Decimal | None
    min_base_idr: Decimal | None
    min_traded_qty: Decimal | None
    maintenance: bool
    suspended: bool
    blocked_reasons: tuple[str, ...]

    @property
    def tradable(self) -> bool:
        return not self.blocked_reasons


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    """Round down to a multiple of `increment`."""
    if increment <= 0:
        raise ValueError("increment must be positive")
    return (value / increment).to_integral_value(rounding=ROUND_FLOOR) * increment


def build_pair_rules(pairs: list[PairInfo], increments: dict[str, Decimal]) -> dict[str, PairRules]:
    out: dict[str, PairRules] = {}
    for p in pairs:
        reasons: list[str] = []
        price_inc = increments.get(p.ticker_id)
        if p.quantity_increment is None or p.quantity_increment <= 0:
            reasons.append("quantity increment missing")
        if price_inc is None or price_inc <= 0:
            reasons.append("price increment missing")
        if p.min_base_idr is None or p.min_traded_qty is None:
            reasons.append("order minimums missing")
        scale = p.raw.get("pricescale")
        if scale is not None and price_inc is not None:
            try:
                if Decimal(str(scale)) != price_inc:
                    # Two endpoints disagree about the price step: do not guess which is right.
                    reasons.append("price increment disagrees with pricescale")
            except InvalidOperation:
                reasons.append("pricescale unreadable")
        if p.maintenance:
            reasons.append("pair in maintenance")
        if p.suspended:
            reasons.append("market suspended")
        out[p.pair] = PairRules(
            pair=p.pair,
            ticker_id=p.ticker_id,
            quantity_increment=p.quantity_increment,
            price_increment=price_inc,
            min_base_idr=p.min_base_idr,
            min_traded_qty=p.min_traded_qty,
            maintenance=p.maintenance,
            suspended=p.suspended,
            blocked_reasons=tuple(reasons),
        )
    return out


def store_pair_rules(session: Session, rules: dict[str, PairRules], now: datetime) -> None:
    for r in rules.values():
        row = session.get(PairRule, r.pair) or PairRule(pair=r.pair)
        row.ticker_id = r.ticker_id
        row.quantity_increment = r.quantity_increment
        row.price_increment = r.price_increment
        row.min_base_idr = r.min_base_idr
        row.min_traded_qty = r.min_traded_qty
        row.maintenance = r.maintenance
        row.suspended = r.suspended
        row.blocked_reasons = list(r.blocked_reasons)
        row.fetched_at = now.astimezone(UTC)
        session.add(row)
    session.flush()


def check_order(rules: PairRules, price: Decimal, quantity: Decimal) -> list[str]:
    """Reasons an order must not be created. Empty means it satisfies the pair's rules."""
    if not rules.tradable:
        return [f"pair blocked: {', '.join(rules.blocked_reasons)}"]
    reasons: list[str] = []
    assert rules.quantity_increment is not None and rules.price_increment is not None
    if quantity <= 0 or price <= 0:
        reasons.append("price and quantity must be positive")
        return reasons
    if quantity != floor_to_increment(quantity, rules.quantity_increment):
        reasons.append("quantity is not a multiple of the quantity increment")
    if price != floor_to_increment(price, rules.price_increment):
        reasons.append("price is not a multiple of the price increment")
    assert rules.min_traded_qty is not None and rules.min_base_idr is not None
    if quantity < rules.min_traded_qty:
        reasons.append("below the minimum quantity")
    if price * quantity < rules.min_base_idr:
        reasons.append("below the minimum order value")
    return reasons


def is_stale(fetched_at: datetime, now: datetime, limit_s: int) -> bool:
    """Data older than the freshness limit is stale by definition, never silently current."""
    return (now - fetched_at).total_seconds() > limit_s
