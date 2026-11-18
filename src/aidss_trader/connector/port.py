"""The venue-neutral surface the rest of the Trader may use to talk to an exchange.

Everything outside `connector/` and the one place that builds a client
(`runtime/assembly.py`) depends on this Protocol, never on a concrete client. A second venue is
then an adapter that satisfies it plus one line in the venue table, not an edit to the order
manager, the reconciler, the kill switch, or the loop.

Two limits are deliberate, and both are about not promising more than exists:

* It is a **spot** port. Orders are `BUY`/`SELL` of a base asset against a quote asset, and an
  account is a set of balances. A derivatives venue (leverage, short positions, margin,
  liquidation, funding) is not a variation on this: its core objects are positions, not
  balances, and its risk rules differ. It gets its own port and its own decision record when the
  owner takes it up (ADR-056), rather than being squeezed in here with optional arguments.
* It carries no withdrawal, deposit, or transfer method, by design (ADR-013). A venue adapter
  that has one must not expose it through this port; `test_exchange_port.py` fails if one
  appears.

Money and quantities are `Decimal` (ADR-025); every result type is in `connector.types`.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol, runtime_checkable

from aidss_trader.connector.types import (
    Account,
    BookTicker,
    Candle,
    MarketSummary,
    OrderInfo,
    PairInfo,
    TradeFill,
)


@runtime_checkable
class ExchangeClient(Protocol):
    # --- time -------------------------------------------------------------------------
    def check_clock(self) -> int:
        """Skew against the exchange in milliseconds; raises if it exceeds the allowed limit."""
        ...

    def get_server_time(self) -> int: ...

    # --- market data (public) -----------------------------------------------------------
    def get_pairs(self) -> list[PairInfo]: ...

    def get_price_increments(self) -> dict[str, Decimal]: ...

    def get_ohlc(self, symbol: str, timeframe: str, start_s: int, end_s: int) -> list[Candle]: ...

    def get_last_prices(self, symbols: Iterable[str] | None = None) -> dict[str, Decimal]: ...

    def get_book_tickers(self, symbols: Iterable[str] | None = None) -> dict[str, BookTicker]: ...

    def get_market_summaries(self) -> dict[str, MarketSummary]:
        """Last price, best bid and ask and 24 hour quote volume for every market, in one call."""
        ...

    # --- account and orders (signed) ----------------------------------------------------
    def get_account(self) -> Account: ...

    def get_open_orders(self, symbol: str | None = None) -> list[OrderInfo]: ...

    def get_order(
        self, symbol: str, *, order_id: int | None = None, client_order_id: str | None = None
    ) -> OrderInfo: ...

    def get_order_history(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[OrderInfo]: ...

    def get_my_trades(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]: ...

    def create_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        client_order_id: str,
        price: Decimal | None = None,
        quantity: Decimal | None = None,
        quote_order_qty: Decimal | None = None,
        time_in_force: str | None = None,
        stp_mode: str | None = None,
    ) -> OrderInfo:
        """Never retried by the adapter: a timeout leaves the outcome unknown (ADR-024)."""
        ...

    def cancel_order(
        self, symbol: str, *, order_id: int | None = None, client_order_id: str | None = None
    ) -> OrderInfo: ...
