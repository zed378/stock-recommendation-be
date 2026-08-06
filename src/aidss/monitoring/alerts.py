"""Conditions worth being told about, and the discipline around saying so.

An alert is the most dangerous surface in this platform. It arrives unbidden,
it is read in seconds, and it is stripped of everything the analysis screen
surrounds a stance with - the counter-evidence, the calibrated confidence, the
disclaimer. A push notification reading "SELL BBCA" is a trading signal no
matter what the rest of the product says about itself.

So the rule here is narrow and absolute: **an alert states what happened, and
the stance travels as data.** `AlertKind` is a closed enum of observations.
Messages are factual sentences. Where a stance is relevant it goes into
`context` as a field, which the interface renders next to a link back to the
full analysis - the place where confidence and conflicting factors live.

The second discipline is deduplication. A condition that is true stays true, so
a rule evaluated every few minutes would fire every few minutes. Each candidate
carries a key describing *which occurrence* it is - the level, the session, the
stance - so a genuinely new crossing is not suppressed along with the repeats.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aidss.db.models import Alert, AlertDirection, AlertKind
from aidss.market.idx_rules import auto_reject_band
from aidss.monitoring.signals import (
    EXTREME_BAND,
    FALSE_BREAKOUT_SESSIONS,
    FAST_MA,
    FOREIGN_FLOW_RATIO,
    GAP_THRESHOLD,
    MIN_REWARD_TO_RISK,
    QUIET_MOVE_LIMIT,
    RANGE_EXPANSION_RATIO,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    SLOW_MA,
    SQUEEZE_PERCENTILE,
    STOCH_OVERBOUGHT,
    STOCH_OVERSOLD,
    VOLUME_SPIKE_RATIO,
    TechnicalSignals,
    foreign_flow_ratio,
    reward_to_risk,
)

#: How close to a level counts as "approached". Relative, so a Rp 100 stock and
#: a Rp 10,000 one are judged the same way.
APPROACH_BAND = Decimal("0.02")

#: A move beyond this multiple of the asset's own recent volatility is unusual
#: *for that asset*. An absolute percentage would flag every small-cap daily
#: and never flag a large-cap having its worst day in years.
UNUSUAL_MOVE_SIGMA = Decimal("2.0")

#: How much of the session's auto-rejection band must be consumed to be worth
#: mentioning.
LIMIT_PROXIMITY_THRESHOLD = Decimal("0.7")


@dataclass(slots=True)
class AlertCandidate:
    """A condition that was met, before it is known to be new."""

    kind: AlertKind
    direction: AlertDirection
    message: str
    dedup_key: str
    observed_price: Decimal | None = None
    reference_price: Decimal | None = None
    context: dict[str, Any] = field(default_factory=dict)


def _session_key(moment: datetime) -> str:
    """Alerts about a session repeat once per session, not once per poll."""
    return moment.astimezone(UTC).date().isoformat()


def _pct(a: Decimal, b: Decimal) -> Decimal | None:
    return (a - b) / b if b else None


def evaluate(
    *,
    asset_id: uuid.UUID,
    ticker: str,
    price: Decimal,
    previous_close: Decimal | None,
    support_levels: list[Decimal] | None = None,
    resistance_levels: list[Decimal] | None = None,
    suggested_stop: Decimal | None = None,
    previous_price: Decimal | None = None,
    daily_volatility: Decimal | None = None,
    stance: str | None = None,
    previous_stance: str | None = None,
    now: datetime | None = None,
) -> list[AlertCandidate]:
    """Which conditions the latest observation meets.

    Pure: takes numbers, returns candidates, touches no database. That is what
    makes every rule below testable without a session, and it is why the rules
    can be read as a list of conditions rather than as a transaction.
    """
    now = now or datetime.now(UTC)
    session_day = _session_key(now)
    candidates: list[AlertCandidate] = []

    # --- stance changed --------------------------------------------------
    #
    # The alert says the stance changed and carries both values as data. It
    # does not say what to do about it, and the message is phrased so that it
    # could not be mistaken for an instruction even read alone.
    if stance and previous_stance and stance != previous_stance:
        candidates.append(
            AlertCandidate(
                kind=AlertKind.STANCE_CHANGED,
                direction=AlertDirection.NONE,
                message=(
                    f"The latest analysis of {ticker} reached a different stance than "
                    f"the previous one. See the analysis for its confidence and the "
                    f"factors arguing against it."
                ),
                dedup_key=f"stance:{asset_id}:{previous_stance}->{stance}",
                observed_price=price,
                context={"from": previous_stance, "to": stance},
            )
        )

    # --- levels ----------------------------------------------------------
    for level in sorted(resistance_levels or []):
        if previous_price is not None and previous_price <= level < price:
            candidates.append(
                AlertCandidate(
                    kind=AlertKind.LEVEL_CROSSED,
                    direction=AlertDirection.UP,
                    message=f"{ticker} traded above a stored resistance level of {level:,.2f}.",
                    dedup_key=f"cross-up:{asset_id}:{level}:{session_day}",
                    observed_price=price,
                    reference_price=level,
                    context={"level_type": "resistance", "level": str(level)},
                )
            )
        elif level > price and _pct(level, price) is not None:
            distance = (level - price) / level
            if 0 <= distance <= APPROACH_BAND:
                candidates.append(
                    AlertCandidate(
                        kind=AlertKind.LEVEL_APPROACHED,
                        direction=AlertDirection.UP,
                        message=(
                            f"{ticker} is within "
                            f"{distance * 100:.1f}% of a stored resistance level "
                            f"of {level:,.2f}."
                        ),
                        dedup_key=f"near-resistance:{asset_id}:{level}:{session_day}",
                        observed_price=price,
                        reference_price=level,
                        context={"level_type": "resistance", "level": str(level)},
                    )
                )

    for level in sorted(support_levels or [], reverse=True):
        if previous_price is not None and previous_price >= level > price:
            candidates.append(
                AlertCandidate(
                    kind=AlertKind.LEVEL_CROSSED,
                    direction=AlertDirection.DOWN,
                    message=f"{ticker} traded below a stored support level of {level:,.2f}.",
                    dedup_key=f"cross-down:{asset_id}:{level}:{session_day}",
                    observed_price=price,
                    reference_price=level,
                    context={"level_type": "support", "level": str(level)},
                )
            )
        elif level < price and level > 0:
            # The mirror of the resistance branch above, which was the only one
            # that existed - so approaching resistance was reported and
            # approaching support, the side people watch for a bounce, was not.
            distance = (price - level) / level
            if 0 <= distance <= APPROACH_BAND:
                candidates.append(
                    AlertCandidate(
                        kind=AlertKind.SUPPORT_APPROACHED,
                        direction=AlertDirection.DOWN,
                        message=(
                            f"{ticker} is within {distance * 100:.1f}% of a stored support "
                            f"level of {level:,.2f}."
                        ),
                        dedup_key=f"near-support:{asset_id}:{level}:{session_day}",
                        observed_price=price,
                        reference_price=level,
                        context={"level_type": "support", "level": str(level)},
                    )
                )

    # --- the level a recommendation named as a stop ----------------------
    #
    # Reported as "reached", not "triggered": nothing is triggered, because
    # nothing here can act. The word choice is the whole distinction.
    if suggested_stop is not None and price <= suggested_stop:
        candidates.append(
            AlertCandidate(
                kind=AlertKind.SUGGESTED_STOP_REACHED,
                direction=AlertDirection.DOWN,
                message=(
                    f"{ticker} reached {price:,.2f}, at or below the level the stored "
                    f"analysis suggested as a stop ({suggested_stop:,.2f})."
                ),
                dedup_key=f"stop:{asset_id}:{suggested_stop}:{session_day}",
                observed_price=price,
                reference_price=suggested_stop,
                context={"suggested_stop": str(suggested_stop)},
            )
        )

    # --- auto-rejection band ---------------------------------------------
    if previous_close is not None:
        band = auto_reject_band(previous_close)
        if band is not None:
            consumed = band.proximity(price)
            if consumed is not None and consumed >= LIMIT_PROXIMITY_THRESHOLD:
                at_ceiling = consumed >= Decimal("0.999")
                candidates.append(
                    AlertCandidate(
                        kind=AlertKind.LIMIT_PROXIMITY,
                        direction=AlertDirection.UP,
                        message=(
                            f"{ticker} has reached the exchange's upper auto-rejection "
                            f"limit for the session ({band.ceiling:,.2f})."
                            if at_ceiling
                            else (
                                f"{ticker} has used {consumed * 100:.0f}% of the session's "
                                f"upward auto-rejection band, which tops out at "
                                f"{band.ceiling:,.2f}."
                            )
                        ),
                        dedup_key=(
                            f"limit:{asset_id}:{session_day}:"
                            f"{'ceiling' if at_ceiling else 'near'}"
                        ),
                        observed_price=price,
                        reference_price=band.ceiling,
                        context={
                            "consumed": str(consumed.quantize(Decimal("0.001"))),
                            "ceiling": str(band.ceiling),
                            "limit_percent": str(band.limit_fraction * 100),
                        },
                    )
                )

    # --- unusual move ------------------------------------------------------
    if previous_close is not None and daily_volatility and daily_volatility > 0:
        move = _pct(price, previous_close)
        if move is not None and abs(move) >= daily_volatility * UNUSUAL_MOVE_SIGMA:
            up = move > 0
            candidates.append(
                AlertCandidate(
                    kind=AlertKind.UNUSUAL_MOVE,
                    direction=AlertDirection.UP if up else AlertDirection.DOWN,
                    message=(
                        f"{ticker} moved {move * 100:+.1f}% against a typical daily range "
                        f"of {daily_volatility * 100:.1f}%."
                    ),
                    dedup_key=f"unusual:{asset_id}:{session_day}:{'up' if up else 'down'}",
                    observed_price=price,
                    reference_price=previous_close,
                    context={"move": str(move.quantize(Decimal("0.0001")))},
                )
            )

    return candidates



def evaluate_signals(
    *,
    asset_id: uuid.UUID,
    ticker: str,
    price: Decimal,
    signals: TechnicalSignals,
    support_levels: list[Decimal] | None = None,
    now: datetime | None = None,
) -> list[AlertCandidate]:
    """Conditions read from the stored daily bars rather than from the quote.

    A second function rather than more parameters on `evaluate`, because these
    share an input and a cadence: they all come from `TechnicalSignals`, and
    they are all statements about a *session* - so they dedupe per session
    while the quote rules dedupe per level or per stance.

    Every rule is stated on two points in time where it can be. "RSI is below
    30" is true on the day it crosses and every day after; "RSI crossed below
    30" happens once. The second is an event, and only events are worth an
    interruption.
    """
    now = now or datetime.now(UTC)
    day = signals.as_of.isoformat() if signals.as_of else _session_key(now)
    out: list[AlertCandidate] = []

    def add(
        kind: AlertKind,
        direction: AlertDirection,
        message: str,
        key: str,
        *,
        reference: Decimal | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        out.append(
            AlertCandidate(
                kind=kind,
                direction=direction,
                message=message,
                dedup_key=f"{key}:{asset_id}:{day}",
                observed_price=price,
                reference_price=reference,
                context=context or {},
            )
        )

    # --- volume ------------------------------------------------------------
    ratio = signals.volume_ratio
    if ratio is not None and ratio >= VOLUME_SPIKE_RATIO:
        move = (
            (price - signals.previous_close) / signals.previous_close
            if signals.previous_close
            else None
        )
        add(
            AlertKind.VOLUME_SPIKE,
            AlertDirection.NONE,
            f"{ticker} traded {ratio:.1f}x its 20-day average volume this session.",
            "volume-spike",
            context={"volume_ratio": str(ratio.quantize(Decimal("0.01")))},
        )
        # The pairing, as its own observation. Busy before the price has run is
        # a different thing to look at from busy because it already has, and a
        # reader filtering for the first cannot get it out of the first alert.
        if move is not None and abs(move) < QUIET_MOVE_LIMIT:
            add(
                AlertKind.VOLUME_SPIKE_QUIET,
                AlertDirection.NONE,
                (
                    f"{ticker} traded {ratio:.1f}x its average volume while the price "
                    f"moved {move * 100:+.1f}% - the volume is ahead of the move so far."
                ),
                "volume-spike-quiet",
                reference=signals.previous_close,
                context={
                    "volume_ratio": str(ratio.quantize(Decimal("0.01"))),
                    "move": str(move.quantize(Decimal("0.0001"))),
                },
            )

    # --- moving average crossings -------------------------------------------
    crossed_up = _crossed_above(
        signals.previous_fast_ma, signals.previous_slow_ma, signals.fast_ma, signals.slow_ma
    )
    crossed_down = _crossed_above(
        signals.previous_slow_ma, signals.previous_fast_ma, signals.slow_ma, signals.fast_ma
    )
    if crossed_up:
        add(
            AlertKind.GOLDEN_CROSS,
            AlertDirection.UP,
            f"{ticker}: the {FAST_MA}-day average crossed above the {SLOW_MA}-day average.",
            "golden-cross",
            reference=signals.slow_ma,
            context={"fast": str(signals.fast_ma), "slow": str(signals.slow_ma)},
        )
    elif crossed_down:
        add(
            AlertKind.DEATH_CROSS,
            AlertDirection.DOWN,
            f"{ticker}: the {FAST_MA}-day average crossed below the {SLOW_MA}-day average.",
            "death-cross",
            reference=signals.slow_ma,
            context={"fast": str(signals.fast_ma), "slow": str(signals.slow_ma)},
        )

    # --- MACD ---------------------------------------------------------------
    macd_up = _crossed_above(
        signals.previous_macd, signals.previous_macd_signal, signals.macd, signals.macd_signal
    )
    macd_down = _crossed_above(
        signals.previous_macd_signal, signals.previous_macd, signals.macd_signal, signals.macd
    )
    if macd_up or macd_down:
        add(
            AlertKind.MACD_CROSSED,
            AlertDirection.UP if macd_up else AlertDirection.DOWN,
            (
                f"{ticker}: MACD crossed {'above' if macd_up else 'below'} its signal line."
            ),
            f"macd-{'up' if macd_up else 'down'}",
            context={"macd": str(signals.macd), "signal": str(signals.macd_signal)},
        )

    # --- momentum bands -----------------------------------------------------
    #
    # Stated on the crossing, not on the state. "RSI is below 30" stays true
    # for as long as the condition lasts, so a rule written that way fires
    # every session of a downtrend and stops being read.
    for kind, direction, current, previous, threshold, name, below in (
        (
            AlertKind.RSI_OVERSOLD, AlertDirection.DOWN,
            signals.rsi, signals.previous_rsi, RSI_OVERSOLD, "RSI", True,
        ),
        (
            AlertKind.RSI_OVERBOUGHT, AlertDirection.UP,
            signals.rsi, signals.previous_rsi, RSI_OVERBOUGHT, "RSI", False,
        ),
        (
            AlertKind.STOCHASTIC_OVERSOLD, AlertDirection.DOWN,
            signals.stochastic_k, signals.previous_stochastic_k, STOCH_OVERSOLD,
            "Stochastic %K", True,
        ),
        (
            AlertKind.STOCHASTIC_OVERBOUGHT, AlertDirection.UP,
            signals.stochastic_k, signals.previous_stochastic_k, STOCH_OVERBOUGHT,
            "Stochastic %K", False,
        ),
    ):
        if current is None or previous is None:
            continue
        entered = (
            previous >= threshold > current if below else previous <= threshold < current
        )
        if entered:
            add(
                kind,
                direction,
                (
                    f"{ticker}: {name} fell to {current:.1f}, below the conventional "
                    f"{threshold:.0f} line."
                    if below
                    else (
                        f"{ticker}: {name} rose to {current:.1f}, above the conventional "
                        f"{threshold:.0f} line."
                    )
                ),
                kind.value.replace("_", "-"),
                context={"value": str(current.quantize(Decimal("0.01")))},
            )

    # --- gaps ---------------------------------------------------------------
    if signals.session_open is not None and signals.previous_close:
        gap = (signals.session_open - signals.previous_close) / signals.previous_close
        if abs(gap) >= GAP_THRESHOLD:
            up = gap > 0
            add(
                AlertKind.GAP_UP if up else AlertKind.GAP_DOWN,
                AlertDirection.UP if up else AlertDirection.DOWN,
                (
                    f"{ticker} opened {gap * 100:+.1f}% away from the previous close "
                    f"({signals.previous_close:,.2f})."
                ),
                "gap-up" if up else "gap-down",
                reference=signals.previous_close,
                context={"gap": str(gap.quantize(Decimal("0.0001")))},
            )

    # --- a break that did not hold ------------------------------------------
    if signals.failed_breakout_level is not None:
        level = signals.failed_breakout_level
        add(
            AlertKind.FALSE_BREAKOUT,
            AlertDirection.DOWN,
            (
                f"{ticker} traded above {level:,.2f} within the last "
                f"{FALSE_BREAKOUT_SESSIONS} sessions and has closed back below it."
            ),
            "false-breakout",
            reference=level,
            context={"level": str(level)},
        )

    # --- position in the year's range ----------------------------------------
    for level, kind, direction, word in (
        (signals.year_high, AlertKind.AT_52_WEEK_HIGH, AlertDirection.UP, "high"),
        (signals.year_low, AlertKind.AT_52_WEEK_LOW, AlertDirection.DOWN, "low"),
    ):
        if level is None or level <= 0:
            continue
        distance = abs(price - level) / level
        if distance <= EXTREME_BAND:
            add(
                kind,
                direction,
                (
                    f"{ticker} is within {distance * 100:.1f}% of its 52-week {word} "
                    f"of {level:,.2f}."
                ),
                f"52w-{word}",
                reference=level,
                context={"level": str(level)},
            )

    # --- volatility ----------------------------------------------------------
    #
    # The squeeze states the compression and stops there. "Bands are narrow" is
    # an observation; "a big move is coming" is a forecast, and the direction of
    # the resolution is precisely what a squeeze does not tell anybody.
    if signals.bandwidth_percentile is not None and (
        signals.bandwidth_percentile <= SQUEEZE_PERCENTILE
    ):
        add(
            AlertKind.VOLATILITY_SQUEEZE,
            AlertDirection.NONE,
            (
                f"{ticker}: Bollinger bands are narrower than on "
                f"{(1 - signals.bandwidth_percentile) * 100:.0f}% of recent sessions."
            ),
            "squeeze",
            context={
                "bandwidth": str(signals.bandwidth),
                "percentile": str(signals.bandwidth_percentile),
            },
        )

    if signals.range_ratio is not None and signals.range_ratio >= RANGE_EXPANSION_RATIO:
        add(
            AlertKind.RANGE_EXPANSION,
            AlertDirection.NONE,
            (
                f"{ticker} traded a range {signals.range_ratio:.1f}x its average true "
                f"range this session."
            ),
            "range-expansion",
            context={"range_ratio": str(signals.range_ratio.quantize(Decimal("0.01")))},
        )

    # --- support with a higher low on RSI ------------------------------------
    #
    # One alert rather than two, because either half alone says much less than
    # the pair. "Near support" is a location; "RSI made a higher low" is a
    # measurement; together they are the setup people actually watch for.
    if signals.bullish_divergence:
        near = _nearest_support_within_band(price, support_levels)
        if near is not None:
            add(
                AlertKind.SUPPORT_WITH_DIVERGENCE,
                AlertDirection.NONE,
                (
                    f"{ticker} is near a stored support level of {near:,.2f} while RSI "
                    f"has made a higher low than its previous one."
                ),
                "support-divergence",
                reference=near,
                context={"level": str(near), "divergence": "bullish"},
            )

    return out


def evaluate_geometry(
    *,
    asset_id: uuid.UUID,
    ticker: str,
    price: Decimal,
    support_levels: list[Decimal] | None,
    resistance_levels: list[Decimal] | None,
    now: datetime | None = None,
) -> list[AlertCandidate]:
    """Where price sits between the nearest stored levels.

    Its own function because it needs both sides, which none of the other rules
    do. Stated as a measurement - "twice as far up as down" - and not as a
    suggestion to take the trade: the ratio is arithmetic on two levels, and it
    knows nothing about whether either will hold.
    """
    now = now or datetime.now(UTC)
    computed = reward_to_risk(price, support_levels, resistance_levels)
    if computed is None:
        return []

    ratio, support, resistance = computed
    if ratio < MIN_REWARD_TO_RISK:
        return []

    return [
        AlertCandidate(
            kind=AlertKind.REWARD_TO_RISK_REACHED,
            direction=AlertDirection.NONE,
            message=(
                f"{ticker} at {price:,.2f} sits {ratio:.1f}x further from the nearest "
                f"stored resistance ({resistance:,.2f}) than from the nearest stored "
                f"support ({support:,.2f})."
            ),
            dedup_key=f"reward-risk:{asset_id}:{support}:{resistance}:{_session_key(now)}",
            observed_price=price,
            reference_price=support,
            context={
                "ratio": str(ratio.quantize(Decimal("0.01"))),
                "support": str(support),
                "resistance": str(resistance),
            },
        )
    ]


def evaluate_trailing_stop(
    *,
    asset_id: uuid.UUID,
    ticker: str,
    price: Decimal,
    peak_since_entry: Decimal | None,
    drop_fraction: Decimal,
    now: datetime | None = None,
) -> list[AlertCandidate]:
    """Price fell a set distance from its peak since a holding was opened.

    Per user rather than per asset, and that is the whole reason it is separate:
    the peak is measured from *their* entry, so two people holding the same
    issuer since different dates are watching different numbers.

    Named "reached", like the suggested stop: nothing is triggered, because
    nothing here can act.
    """
    now = now or datetime.now(UTC)
    if peak_since_entry is None or peak_since_entry <= 0 or drop_fraction <= 0:
        return []

    drop = (peak_since_entry - price) / peak_since_entry
    if drop < drop_fraction:
        return []

    return [
        AlertCandidate(
            kind=AlertKind.TRAILING_STOP_REACHED,
            direction=AlertDirection.DOWN,
            message=(
                f"{ticker} is {drop * 100:.1f}% below its peak of {peak_since_entry:,.2f} "
                f"since you recorded the holding."
            ),
            dedup_key=f"trailing:{asset_id}:{peak_since_entry}:{_session_key(now)}",
            observed_price=price,
            reference_price=peak_since_entry,
            context={
                "peak": str(peak_since_entry),
                "drop": str(drop.quantize(Decimal("0.0001"))),
                "threshold": str(drop_fraction),
            },
        )
    ]


def evaluate_foreign_flow(
    *,
    asset_id: uuid.UUID,
    ticker: str,
    price: Decimal,
    history: list[Decimal],
    now: datetime | None = None,
) -> list[AlertCandidate]:
    """Net foreign buying or selling far above this issuer's own recent size.

    Its own function because its input is a different dataset - the exchange's
    end-of-session record rather than the price bars - and because it is the
    one alert here that can be absent for an ordinary reason: IDX publishes no
    foreign figures for some sessions, and a name with too little history
    simply produces nothing.

    States the flow and its size. It does not say who was buying, which broker,
    or what they intend - none of which is in the data, and all of which is
    what somebody reading the words "smart money" would assume it knew.
    """
    now = now or datetime.now(UTC)
    computed = foreign_flow_ratio(history)
    if computed is None:
        return []

    ratio, latest = computed
    if abs(ratio) < FOREIGN_FLOW_RATIO:
        return []

    accumulating = latest > 0
    return [
        AlertCandidate(
            kind=AlertKind.FOREIGN_FLOW_SPIKE,
            direction=AlertDirection.UP if accumulating else AlertDirection.DOWN,
            message=(
                f"{ticker} recorded net foreign "
                f"{'buying' if accumulating else 'selling'} of "
                f"{abs(latest):,.0f} shares, about {abs(ratio):.1f}x the size of its "
                f"recent sessions."
            ),
            dedup_key=f"foreign-flow:{asset_id}:{_session_key(now)}",
            observed_price=price,
            context={
                "net_foreign": str(latest),
                "ratio": str(ratio.quantize(Decimal("0.01"))),
                "side": "buy" if accumulating else "sell",
            },
        )
    ]


def _crossed_above(
    previous_a: Decimal | None,
    previous_b: Decimal | None,
    current_a: Decimal | None,
    current_b: Decimal | None,
) -> bool:
    """Whether A went from at-or-below B to above it.

    All four values are required. A crossing needs two points in time, and
    treating a missing previous value as "was below" would report a cross on
    the first session there was enough history to compute either line - which
    is a property of the data starting, not of the market.
    """
    if None in (previous_a, previous_b, current_a, current_b):
        return False
    return previous_a <= previous_b and current_a > current_b  # type: ignore[operator]


def _nearest_support_within_band(
    price: Decimal, support_levels: list[Decimal] | None
) -> Decimal | None:
    for level in sorted(support_levels or [], reverse=True):
        if level <= 0 or level > price:
            continue
        if (price - level) / level <= APPROACH_BAND:
            return level
    return None


def record(
    session: Session,
    user_id: uuid.UUID,
    asset_id: uuid.UUID,
    candidates: list[AlertCandidate],
) -> list[Alert]:
    """Store the candidates that are new for this user.

    Deduplicated per user, because two people following the same asset should
    each be told once - a shared key would mean whoever polls second is never
    alerted at all.

    The unique index is the arbiter, not the pre-check: two workers polling the
    same asset concurrently would both pass a check-then-insert.
    """
    stored: list[Alert] = []
    for candidate in candidates:
        key = f"{user_id}:{candidate.dedup_key}"
        existing = session.scalar(select(Alert).where(Alert.dedup_key == key))
        if existing is not None:
            continue

        alert = Alert(
            user_id=user_id,
            asset_id=asset_id,
            kind=candidate.kind,
            direction=candidate.direction,
            observed_price=candidate.observed_price,
            reference_price=candidate.reference_price,
            message=candidate.message,
            context=candidate.context or None,
            dedup_key=key,
        )
        session.add(alert)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            continue
        stored.append(alert)
    return stored


def today() -> date:
    return datetime.now(UTC).date()
