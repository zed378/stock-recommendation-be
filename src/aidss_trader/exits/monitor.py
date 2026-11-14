"""Exit monitor (ADR-007): bot-side stops, because the exchange has none.

With the bot down there is no stop, so the monitor treats its own silence as the
risk. One price call per cycle covers every position; a position whose price is
missing or stale is reported `unprotected` rather than assumed safe, and after
`watchdog_cycles` consecutive misses the monitor raises `UnprotectedAlert`.

Rules:

* A stop is never moved away from the price (never widened). Tightening is fine.
* At most one exit is requested per position; the request stays pending until the
  caller clears it, so a slow fill cannot produce a second sell.
* The monitor decides *that* a stop has triggered. The sell itself goes through
  the order manager's EMERGENCY profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class WatchedPosition:
    pair: str
    quantity: Decimal
    stop_price: Decimal


@dataclass(frozen=True, slots=True)
class ExitRequest:
    pair: str
    quantity: Decimal
    stop_price: Decimal
    observed_price: Decimal
    reason: str = "stop_hit"


@dataclass(frozen=True, slots=True)
class CycleReport:
    exits: list[ExitRequest]
    unprotected: list[str]
    alerts: list[str]


class StopWidenRefused(ValueError):
    pass


@dataclass(slots=True)
class ExitMonitor:
    watchdog_cycles: int
    pending: set[str] = field(default_factory=set)
    _misses: dict[str, int] = field(default_factory=dict)

    def tighten_stop(self, current: Decimal, proposed: Decimal) -> Decimal:
        """Long positions only: a stop may rise, never fall."""
        if proposed < current:
            raise StopWidenRefused(f"stop {proposed} would widen the loss limit {current}")
        return proposed

    def clear(self, pair: str) -> None:
        self.pending.discard(pair)

    def cycle(
        self,
        positions: list[WatchedPosition],
        prices: dict[str, Decimal] | None,
        *,
        price_time: datetime | None,
        now: datetime,
        max_age_s: float,
    ) -> CycleReport:
        """`prices` is None when the single price call failed."""
        fresh = (
            prices is not None
            and price_time is not None
            and (now - price_time).total_seconds() <= max_age_s
        )
        exits: list[ExitRequest] = []
        unprotected: list[str] = []
        alerts: list[str] = []
        watched = {p.pair for p in positions}
        for gone in set(self._misses) - watched:
            del self._misses[gone]
        for pos in positions:
            price = prices.get(pos.pair) if (fresh and prices) else None
            if price is None:
                misses = self._misses.get(pos.pair, 0) + 1
                self._misses[pos.pair] = misses
                unprotected.append(pos.pair)
                if misses >= self.watchdog_cycles:
                    alerts.append(
                        f"UnprotectedAlert: {pos.pair} has had no fresh price for {misses} cycles"
                    )
                continue
            self._misses[pos.pair] = 0
            if price <= pos.stop_price and pos.pair not in self.pending:
                self.pending.add(pos.pair)
                exits.append(ExitRequest(pos.pair, pos.quantity, pos.stop_price, price))
        return CycleReport(exits, unprotected, alerts)
