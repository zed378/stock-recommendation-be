"""Paper executor (docs/05-MODULE-SPECIFICATIONS/06). Conservative by design.

Paper must not look better than live would. A LIMIT order fills only if price
trades THROUGH it (strictly), not merely touches it. Costs and slippage are the
owner's numbers (OQ-5): nothing here has a default, and applying tax and
clearing as a percentage of the quote value is an assumption to be checked
against real fills.

Paper and backtest share this executor. It never touches the connector.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aidss_trader.connector.types import BookTicker, Candle


@dataclass(frozen=True, slots=True)
class CostModel:
    maker_fee_pct: Decimal
    taker_fee_pct: Decimal
    tax_pct: Decimal
    clearing_pct: Decimal

    def cost(self, quote_value: Decimal, *, maker: bool) -> Decimal:
        fee = self.maker_fee_pct if maker else self.taker_fee_pct
        return quote_value * (fee + self.tax_pct + self.clearing_pct) / 100


@dataclass(frozen=True, slots=True)
class PaperConfig:
    slippage_pct: Decimal  # applied to MARKET fills, against the trader
    partial_fill_fraction: (
        Decimal  # of the remaining quantity filled per candle that trades through
    )
    costs: CostModel

    def __post_init__(self) -> None:
        if not 0 < self.partial_fill_fraction <= 1:
            raise ValueError("partial_fill_fraction must be in (0, 1]")
        if self.slippage_pct < 0:
            raise ValueError("slippage_pct cannot be negative")


@dataclass(frozen=True, slots=True)
class PaperFill:
    price: Decimal
    quantity: Decimal
    maker: bool
    cost: Decimal


class PaperRejected(Exception):
    """A MOC order that would have matched immediately (the exchange cancels it)."""


class PaperExecutor:
    def __init__(self, config: PaperConfig) -> None:
        self._cfg = config

    def limit_against_candle(
        self, side: str, price: Decimal, remaining: Decimal, candle: Candle
    ) -> PaperFill | None:
        """Fill (part of) a resting LIMIT order against a later candle, or None."""
        through = candle.low < price if side == "BUY" else candle.high > price
        if not through:
            return None
        qty = remaining * self._cfg.partial_fill_fraction
        return PaperFill(price, qty, True, self._cfg.costs.cost(qty * price, maker=True))

    def check_moc(self, side: str, price: Decimal, book: BookTicker) -> None:
        crosses = price >= book.ask_price if side == "BUY" else price <= book.bid_price
        if crosses:
            raise PaperRejected("MOC order would match immediately")

    def market(self, side: str, quantity: Decimal, reference: Decimal) -> PaperFill:
        """A MARKET fill at the reference price moved against the trader by the allowance."""
        slip = self._cfg.slippage_pct / 100
        price = reference * (1 + slip) if side == "BUY" else reference * (1 - slip)
        return PaperFill(
            price, quantity, False, self._cfg.costs.cost(quantity * price, maker=False)
        )
