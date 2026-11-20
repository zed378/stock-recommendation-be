"""Follow a signal to a simulated outcome, the way the statistician's protocol asks (ADR-067).

Given a signal and the closed 4H candles after it, decide what a follower would have got:

* **Fill** at the open of the first candle after the signal, with slippage against the trader. If
  that price has drifted more than `drift_r` of the stop distance from the signal's entry, or is
  already beyond the stop, the follower does not trade: SKIPPED_DRIFT (the same guard the client
  applies, so the published entry is not what is measured).
* **Ladder**: 50% at TP1, 30% at TP2, 20% at TP3. After TP1 the stop moves to the fill price
  (break-even), as the client does.
* **Order inside a bar is unknowable, so it is pessimistic**: the stop is tested before any
  target on every candle, and after a target moves the stop to break-even, that candle's low (or
  high, for a short) is tested against the new stop too.
* **Costs**: `fee_pct` and `slippage_pct` per side on the whole position, charged once at entry and
  once at exit, converted into R. Nothing is net of costs unless it says so; `gross_r` and `net_r`
  are both kept.
* **Time stop**: after `max_hold_bars` candles what is left closes at that candle's close.

The result is recomputed from scratch each time from the candles, so it is deterministic and the
tracker can be run twice without changing the answer. Every result is a SIMULATION.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aidss.domain.types import Candle

WEIGHTS = (0.5, 0.3, 0.2)

PENDING, OPEN, CLOSED, SKIPPED = "PENDING", "OPEN", "CLOSED", "SKIPPED"


@dataclass(frozen=True, slots=True)
class SimParams:
    fee_pct: float  # per side
    slippage_pct: float  # per side
    drift_r: float
    max_hold_bars: int


@dataclass(frozen=True, slots=True)
class Outcome:
    state: str  # PENDING | OPEN | CLOSED | SKIPPED
    outcome: str | None  # SL, BE_AFTER_TP1, STOP_AFTER_TP2, TP3, EXPIRED, SKIPPED_DRIFT
    tp_hits: int
    fill_price: float | None
    gross_r: float | None
    net_r: float | None
    bars_held: int
    closed_index: int | None  # index into the candles passed, when closed


def simulate(
    side: str,
    entry: float,
    stop: float,
    tps: Sequence[float],
    after: Sequence[Candle],
    sim: SimParams,
) -> Outcome:
    long = side == "LONG"
    sign = 1.0 if long else -1.0
    risk = abs(entry - stop)
    if risk <= 0:
        return Outcome(SKIPPED, "SKIPPED_DRIFT", 0, None, None, None, 0, None)
    if not after:
        return Outcome(PENDING, None, 0, None, None, None, 0, None)

    slip = sim.slippage_pct / 100.0
    first_open = float(after[0].open)
    fill = first_open * (1.0 + slip) if long else first_open * (1.0 - slip)
    drift = abs(fill - entry) / risk
    already_stopped = (fill <= stop) if long else (fill >= stop)
    if drift > sim.drift_r or already_stopped:
        return Outcome(SKIPPED, "SKIPPED_DRIFT", 0, fill, None, None, 0, None)

    remaining = 1.0
    realised = 0.0  # R from closed legs
    stop_now = stop
    hits = 0
    cost_r = ((sim.fee_pct + sim.slippage_pct) / 100.0 * 2.0 * fill) / risk

    def leg_r(exit_price: float, weight: float) -> float:
        return weight * sign * (exit_price - fill) / risk

    def result(outcome: str, index: int, bars: int) -> Outcome:
        net = realised - cost_r
        return Outcome(CLOSED, outcome, hits, fill, round(realised, 6), round(net, 6), bars, index)

    for i, candle in enumerate(after):
        o, h, low, c = (
            float(candle.open),
            float(candle.high),
            float(candle.low),
            float(candle.close),
        )
        bars = i + 1

        def stop_hit(level: float, low: float = low, h: float = h) -> bool:
            return low <= level if long else h >= level

        if stop_hit(stop_now):
            # a gap through the stop fills at the open, not at the stop
            exit_price = min(o, stop_now) if long else max(o, stop_now)
            realised += leg_r(exit_price, remaining)
            remaining = 0.0
            name = "SL" if hits == 0 else ("BE_AFTER_TP1" if hits == 1 else "STOP_AFTER_TP2")
            return result(name, i, bars)

        while hits < 3:
            target = tps[hits]
            reached = h >= target if long else low <= target
            if not reached:
                break
            realised += leg_r(target, WEIGHTS[hits])
            remaining -= WEIGHTS[hits]
            hits += 1
            if hits == 1:
                stop_now = fill  # break-even after the first target
            if hits == 3:
                return result("TP3", i, bars)
            if stop_hit(stop_now):  # pessimistic: the new stop is tested in the same bar
                realised += leg_r(stop_now, remaining)
                remaining = 0.0
                return result("BE_AFTER_TP1" if hits == 1 else "STOP_AFTER_TP2", i, bars)

        if bars >= sim.max_hold_bars:
            realised += leg_r(c, remaining)
            remaining = 0.0
            return result("EXPIRED", i, bars)

    gross_open = realised
    unrealised = leg_r(float(after[-1].close), remaining)
    return Outcome(
        OPEN,
        None,
        hits,
        fill,
        round(gross_open + unrealised, 6),
        round(gross_open + unrealised - cost_r, 6),
        len(after),
        None,
    )
