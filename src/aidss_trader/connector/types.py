"""Typed results. Money and quantities are `Decimal`, parsed from strings (ADR-025)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class BookTicker:
    symbol: str
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal


@dataclass(frozen=True, slots=True)
class PairInfo:
    """One entry of `/api/pairs`. Optional fields really are optional in the examples."""

    pair: str  # canonical, e.g. BTCIDR
    ticker_id: str  # btc_idr
    base_asset: str
    quote_asset: str
    quantity_increment: Decimal | None
    min_base_idr: Decimal | None
    min_traded_qty: Decimal | None
    maintenance: bool
    suspended: bool
    maker_fee_pct: Decimal | None
    taker_fee_pct: Decimal | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class Account:
    can_trade: bool
    can_withdraw: bool
    can_withdraw_fiat: bool
    balances: dict[str, tuple[Decimal, Decimal]]  # asset -> (free, locked)
    # The exchange's account id is deliberately not carried: it must never be
    # logged, shown, or notified (docs/09-SECURITY-PRIVACY/05).


@dataclass(frozen=True, slots=True)
class OrderInfo:
    symbol: str
    order_id: int | None
    full_order_id: str | None
    client_order_id: str | None
    side: str
    type: str | None
    price: Decimal | None
    orig_qty: Decimal
    executed_qty: Decimal
    status: str | None  # NEW, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED (absent on create)
    time_ms: int | None
    cancel_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TradeFill:
    trade_id: str
    full_order_id: str
    client_order_id: str | None
    symbol: str
    price: Decimal
    qty: Decimal
    quote_qty: Decimal
    commission: Decimal  # fees AND taxes combined: the split is not in this endpoint (OQ-5)
    commission_asset: str
    is_buyer: bool
    is_maker: bool
    time_ms: int
