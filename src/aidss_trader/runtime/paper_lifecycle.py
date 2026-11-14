"""Paper trading lifecycle: simulated fills, stops, and exits, kept apart from the live book.

Everything this module writes carries `origin = "PAPER"`. Paper rows are read back only by
`replay_origin(..., "PAPER")`, so a simulated trade can never move a live position, a live
loss limit, or a live drawdown (FR-T28). No exchange call is made here.

The simulation is candle-driven and deliberately pessimistic, the same rules as the
backtest (`backtest/engine.py`):

* An entry rests for exactly one candle, the one after the signal, and fills only if price
  trades strictly through its limit (`PaperExecutor`); otherwise it is abandoned.
* A stop that is hit exits at the worse of the candle's open (a gap) and the stop, plus
  slippage. If the stop and the entry share a candle, the stop is assumed hit.
* A signal exit sells at the next candle's open, plus slippage, with taker costs.
* Costs, slippage, and partial fills come from the owner's settings (OQ-5); with none set
  the simulation does not run.

A cursor per pair records the last candle processed, so a restart neither replays history
nor skips a candle. On the first run the cursor starts at the latest stored candle: a paper
trade is only ever simulated forward from a decision, never retroactively.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.connector.types import Candle as ApiCandle
from aidss_trader.db.models import Fill, OrderIntentRow, OrderRow, PositionStop, TraderSetting
from aidss_trader.market_data.candles import TIMEFRAME_SECONDS
from aidss_trader.market_data.pairs import PairRules, floor_to_increment
from aidss_trader.orders.state import OrderState
from aidss_trader.paper import PaperExecutor
from aidss_trader.runtime import accounting
from aidss_trader.runtime.settings_store import PaperSettings

CURSOR_PREFIX = "paper_cursor:"
EXIT_DELAY = timedelta(seconds=1)  # an exit is later than the fill it follows, for replay order


@dataclass(slots=True)
class PaperAdvance:
    candles: int = 0
    entries: int = 0
    exits: int = 0
    unfilled: int = 0


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _signal_open(identity: str) -> datetime | None:
    """The identity is `version|pair|candle_open_iso|side`; the candle is the signal's."""
    try:
        return _aware(datetime.fromisoformat(identity.split("|")[2]))
    except (IndexError, ValueError):
        return None


class PaperBook:
    def __init__(self, settings: PaperSettings, timeframe: str = "4H") -> None:
        self._exec = PaperExecutor(settings.config)
        self._tf_s = TIMEFRAME_SECONDS[timeframe]

    # ----------------------------------------------------------------- cursor

    @staticmethod
    def _cursor(s: Session, pair: str) -> datetime | None:
        row = s.get(TraderSetting, CURSOR_PREFIX + pair)
        return None if row is None else _aware(datetime.fromisoformat(row.value["at"]))

    @staticmethod
    def _set_cursor(s: Session, pair: str, at: datetime) -> None:
        # Operational state, not an owner setting: written without an audit row.
        row = s.get(TraderSetting, CURSOR_PREFIX + pair)
        value = {"at": at.isoformat()}
        now = datetime.now(UTC)
        if row is None:
            s.add(
                TraderSetting(
                    key=CURSOR_PREFIX + pair, value=value, updated_at=now, updated_by="paper"
                )
            )
        else:
            row.value, row.updated_at = value, now

    # ---------------------------------------------------------------- advance

    def advance(
        self, s: Session, pair: str, candles: Sequence[ApiCandle], rules: PairRules | None
    ) -> PaperAdvance:
        out = PaperAdvance()
        if not candles:
            return out
        cursor = self._cursor(s, pair)
        if cursor is None:
            self._set_cursor(s, pair, candles[-1].open_time)
            s.flush()
            return out
        for c in (c for c in candles if _aware(c.open_time) > cursor):
            self._stop_check(s, pair, c, out)
            self._settle_pending(s, pair, c, rules, out)
            cursor = _aware(c.open_time)
            out.candles += 1
        self._set_cursor(s, pair, cursor)
        s.flush()
        return out

    # ---------------------------------------------------------------- helpers

    def _position_qty(self, s: Session, pair: str) -> Decimal:
        positions, _ = accounting.replay_origin(s, "PAPER")
        pos = positions.get(pair)
        return pos.quantity if pos else Decimal(0)

    def _record(
        self,
        s: Session,
        intent_identity: str | None,
        pair: str,
        side: str,
        order_type: str,
        price: Decimal,
        qty: Decimal,
        purpose: str,
        at: datetime,
        cost: Decimal,
        maker: bool,
        state: OrderState,
    ) -> None:
        tag = hashlib.sha256(
            f"{intent_identity}|{pair}|{side}|{purpose}|{at.isoformat()}".encode()
        ).hexdigest()
        order = OrderRow(
            intent_identity=intent_identity,
            origin="PAPER",
            pair=pair,
            side=side,
            type=order_type,
            price=price if order_type == "LIMIT" else None,
            quantity=qty,
            client_order_id="pp" + tag[:30],
            executed_qty=qty,
            state=state.value,
            purpose=purpose,
            submitted_at=at,
            updated_at=at,
        )
        s.add(order)
        s.flush()
        s.add(
            Fill(
                order_id=order.id,
                origin="PAPER",
                exchange_trade_id="paper-" + tag[:24],
                pair=pair,
                side=side,
                price=price,
                quantity=qty,
                quote_quantity=price * qty,
                is_maker=maker,
                commission=cost,
                executed_at=at,
            )
        )
        s.flush()

    def _sell(
        self,
        s: Session,
        pair: str,
        qty: Decimal,
        reference: Decimal,
        purpose: str,
        at: datetime,
        identity: str | None,
    ) -> None:
        fill = self._exec.market("SELL", qty, reference)
        self._record(
            s,
            identity,
            pair,
            "SELL",
            "MARKET",
            fill.price,
            fill.quantity,
            purpose,
            at,
            fill.cost,
            False,
            OrderState.FILLED,
        )

    # ------------------------------------------------------------------ steps

    def _stop_check(self, s: Session, pair: str, c: ApiCandle, out: PaperAdvance) -> None:
        stop = s.scalar(
            select(PositionStop).where(PositionStop.pair == pair, PositionStop.origin == "PAPER")
        )
        qty = self._position_qty(s, pair)
        if stop is None or qty <= 0 or c.low > stop.stop_price:
            return
        self._sell(
            s,
            pair,
            qty,
            min(c.open, stop.stop_price),
            "STOP",
            _aware(c.open_time) + EXIT_DELAY,
            None,
        )
        out.exits += 1

    def _settle_pending(
        self, s: Session, pair: str, c: ApiCandle, rules: PairRules | None, out: PaperAdvance
    ) -> None:
        opened = _aware(c.open_time)
        pending = s.scalars(
            select(OrderIntentRow)
            .where(
                OrderIntentRow.origin == "PAPER",
                OrderIntentRow.pair == pair,
                OrderIntentRow.state == "PAPER_RECORDED",
            )
            .order_by(OrderIntentRow.created_at)
        )
        for intent in pending:
            signal_open = _signal_open(intent.identity)
            if signal_open is None or opened < signal_open + timedelta(seconds=self._tf_s):
                continue  # the candle after the signal has not closed yet
            if opened > signal_open + timedelta(seconds=self._tf_s):
                intent.state = "PAPER_EXPIRED"  # missed its one candle (a gap or downtime)
                continue
            if intent.side == "BUY":
                self._settle_buy(s, intent, pair, c, rules, out)
            else:
                self._settle_sell(s, intent, pair, c, out)

    def _settle_buy(
        self,
        s: Session,
        intent: OrderIntentRow,
        pair: str,
        c: ApiCandle,
        rules: PairRules | None,
        out: PaperAdvance,
    ) -> None:
        if self._position_qty(s, pair) > 0:
            intent.state = "PAPER_VOID"  # a position is already open: long-only, one at a time
            return
        price = intent.entry_price.quantize(Decimal("1e-8"))
        qty = intent.quantity.quantize(Decimal("1e-8"))
        fill = self._exec.limit_against_candle("BUY", price, qty, c)
        if fill is not None and rules is not None and rules.quantity_increment:
            fill = type(fill)(
                fill.price,
                floor_to_increment(fill.quantity, rules.quantity_increment),
                fill.maker,
                fill.cost,
            )
        if fill is None or fill.quantity <= 0:
            intent.state = "PAPER_UNFILLED"  # price never traded through the limit
            out.unfilled += 1
            return
        full = fill.quantity >= qty
        at = _aware(c.open_time)
        self._record(
            s,
            intent.identity,
            pair,
            "BUY",
            "LIMIT",
            fill.price,
            fill.quantity,
            "ENTRY",
            at,
            fill.cost,
            True,
            OrderState.FILLED if full else OrderState.CANCELLED,
        )
        intent.state = "PAPER_FILLED"
        out.entries += 1
        if intent.stop_price is not None:
            stop = s.scalar(
                select(PositionStop).where(
                    PositionStop.pair == pair, PositionStop.origin == "PAPER"
                )
            )
            if stop is None:
                s.add(
                    PositionStop(
                        pair=pair, origin="PAPER", stop_price=intent.stop_price, updated_at=at
                    )
                )
            else:
                stop.stop_price, stop.updated_at = intent.stop_price, at
            if c.low <= intent.stop_price:
                # Pessimistic: the intrabar order is unknowable, so the stop is assumed hit.
                self._sell(
                    s,
                    pair,
                    fill.quantity,
                    min(c.open, intent.stop_price),
                    "STOP",
                    at + EXIT_DELAY,
                    None,
                )
                out.exits += 1

    def _settle_sell(
        self, s: Session, intent: OrderIntentRow, pair: str, c: ApiCandle, out: PaperAdvance
    ) -> None:
        held = self._position_qty(s, pair)
        if held <= 0:
            intent.state = (
                "PAPER_VOID"  # nothing left to sell, for instance the stop got there first
            )
            return
        qty = min(held, intent.quantity.quantize(Decimal("1e-8")))
        self._sell(s, pair, qty, c.open, "EXIT", _aware(c.open_time), intent.identity)
        intent.state = "PAPER_FILLED"
        out.exits += 1
