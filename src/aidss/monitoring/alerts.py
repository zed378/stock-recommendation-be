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
