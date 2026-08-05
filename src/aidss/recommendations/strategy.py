"""What a stance means depends on whether you already hold the asset.

A `hold` on something you own and a `hold` on something you do not are the same
word describing two different situations: the first says stay, the second says
there is no reason to start. One label answering both questions is why people
read a recommendation and still ask "so what do I do?".

So both readings are produced, always, side by side. Not the one matching the
reader's position - both. Seeing the case you are *not* in is what makes the
asymmetry visible: an asset worth keeping but not worth buying today is a real
and common situation, and a screen that showed only your own side would hide it.

**Derived, never asked.** This is a deterministic projection of a stored
recommendation onto two situations. A second model call could contradict the
first - saying `buy` and then advising an exit - and there would be no way to
tell which was wrong. Everything below follows from the label, the levels, and
the confidence that were already validated and stored.

**Stances, not orders.** Every phrasing here describes a position and the
condition attached to it. `entry_candidate`, not "buy now". `exit_candidate`,
not "sell". The platform cannot place an order and does not tell anyone to;
Section 5.4 puts the wording under the same rule as the labels themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aidss.domain.types import RecommendationLabel


class PositionState(StrEnum):
    """The two situations a reader can be in."""

    HOLDING = "holding"
    NOT_HOLDING = "not_holding"


class Stance(StrEnum):
    """What the recommendation implies for one situation.

    Named as positions and candidacies rather than actions. `trim` and `reduce`
    describe a resulting position; "sell 30%" would describe an order.
    """

    #: Not holding
    ENTRY_CANDIDATE = "entry_candidate"
    WAIT_FOR_LEVEL = "wait_for_level"
    NO_ENTRY_BASIS = "no_entry_basis"
    AVOID = "avoid"

    #: Holding
    MAINTAIN = "maintain"
    ACCUMULATE_CANDIDATE = "accumulate_candidate"
    TRIM_CANDIDATE = "trim_candidate"
    EXIT_CANDIDATE = "exit_candidate"


#: A stance strong enough to warrant an entry needs evidence behind it. Below
#: this, a `buy` becomes "wait for a level" rather than "enter": Section 5.4
#: already refuses a strong label on thin evidence, and the same reasoning
#: applies to acting on a weak one.
ENTRY_CONFIDENCE_FLOOR = 55.0


@dataclass(frozen=True, slots=True)
class Guidance:
    """One situation's reading of the recommendation."""

    position: PositionState
    stance: Stance
    #: Why this stance follows, in one sentence.
    rationale: str
    #: What has to be true. Empty when the stance is unconditional.
    conditions: list[str] = field(default_factory=list)
    #: What would make this stance wrong. Never empty: a stance with no stated
    #: invalidation is one that can never be shown to have been mistaken, and
    #: those are the ones people hold on to longest.
    invalidated_if: list[str] = field(default_factory=list)
    #: Levels that matter for this situation, if the analysis produced any.
    reference_levels: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position.value,
            "stance": self.stance.value,
            "rationale": self.rationale,
            "conditions": list(self.conditions),
            "invalidated_if": list(self.invalidated_if),
            "reference_levels": dict(self.reference_levels),
        }


@dataclass(frozen=True, slots=True)
class StrategyView:
    """Both readings, plus the caveat that applies to both."""

    label: RecommendationLabel
    confidence: float
    not_holding: Guidance
    holding: Guidance
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label.value,
            "confidence": self.confidence,
            "not_holding": self.not_holding.as_dict(),
            "holding": self.holding.as_dict(),
            "disclaimer": self.disclaimer,
        }


STRATEGY_DISCLAIMER = (
    "Informational only and not investment advice. These are stances with the "
    "conditions attached to them, not instructions: this platform places no "
    "orders and is connected to no broker. Position sizing, timing, and the "
    "decision itself remain yours."
)


def _fmt(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)):,.2f}"


def _levels(
    support: Decimal | None,
    resistance: Decimal | None,
    target: Decimal | None,
    stop: Decimal | None,
) -> dict[str, str]:
    pairs = {
        "support": _fmt(support),
        "resistance": _fmt(resistance),
        "target": _fmt(target),
        "suggested_stop": _fmt(stop),
    }
    return {key: value for key, value in pairs.items() if value is not None}


def _not_holding(
    label: RecommendationLabel,
    confidence: float,
    levels: dict[str, str],
) -> Guidance:
    support = levels.get("support")
    resistance = levels.get("resistance")

    invalidation = (
        [f"price closes below support at {support}"]
        if support
        else ["the level the thesis rests on gives way"]
    )

    if label in (RecommendationLabel.STRONG_BUY, RecommendationLabel.BUY):
        if confidence < ENTRY_CONFIDENCE_FLOOR:
            return Guidance(
                position=PositionState.NOT_HOLDING,
                stance=Stance.WAIT_FOR_LEVEL,
                rationale=(
                    f"The stance is {label.value} but calibrated confidence is "
                    f"{confidence:.0f}, below the {ENTRY_CONFIDENCE_FLOOR:.0f} this "
                    "platform treats as enough evidence to favour starting a position."
                ),
                conditions=[
                    "more of the evidence sources agree, raising confidence",
                    f"price pulls back towards support at {support}" if support else
                    "a clearer level to work against appears",
                ],
                invalidated_if=invalidation,
                reference_levels=levels,
            )
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.ENTRY_CANDIDATE,
            rationale=(
                f"A {label.value} stance at {confidence:.0f} confidence describes an "
                "asset the evidence currently favours, which is what makes it a "
                "candidate to consider rather than one to watch."
            ),
            conditions=[
                f"a defined level to work against - support sits at {support}"
                if support
                else "a defined level to work against",
                "the position size fits your own concentration limits, which this "
                "analysis knows nothing about",
            ],
            invalidated_if=invalidation,
            reference_levels=levels,
        )

    if label is RecommendationLabel.WATCHLIST:
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.WAIT_FOR_LEVEL,
            rationale=(
                "A watchlist stance means the case is not yet made either way - "
                "worth following, without a basis to start today."
            ),
            conditions=[
                f"price clears resistance at {resistance} and holds" if resistance
                else "the price structure resolves in one direction",
                f"or price reaches support at {support} with the thesis intact"
                if support
                else "or a clearer entry level forms",
            ],
            invalidated_if=["the reason for following it stops applying"],
            reference_levels=levels,
        )

    if label is RecommendationLabel.HOLD:
        return Guidance(
            position=PositionState.NOT_HOLDING,
            stance=Stance.NO_ENTRY_BASIS,
            rationale=(
                "A hold describes staying where you are. For someone with no "
                "position, staying where you are means not starting one - the same "
                "stance reads differently from the two sides."
            ),
            conditions=["a directional case forms in either direction"],
            invalidated_if=["the analysis moves off neutral"],
            reference_levels=levels,
        )

    # reduce / sell
    return Guidance(
        position=PositionState.NOT_HOLDING,
        stance=Stance.AVOID,
        rationale=(
            f"A {label.value} stance describes evidence pointing down. There is no "
            "reading of it that favours starting a position."
        ),
        conditions=[],
        invalidated_if=["the analysis turns, which would be a different stance entirely"],
        reference_levels=levels,
    )


def _holding(
    label: RecommendationLabel,
    confidence: float,
    levels: dict[str, str],
) -> Guidance:
    support = levels.get("support")
    target = levels.get("target")
    stop = levels.get("suggested_stop")

    stop_line = (
        f"price reaches the suggested stop at {stop}"
        if stop
        else (f"price closes below support at {support}" if support else
              "the level the thesis rests on gives way")
    )

    if label is RecommendationLabel.STRONG_BUY:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.ACCUMULATE_CANDIDATE,
            rationale=(
                f"The evidence favours the asset at {confidence:.0f} confidence, so an "
                "existing position has no case against it and adding is a candidate."
            ),
            conditions=[
                "adding would not push this holding past your own concentration limit",
                f"a pullback towards support at {support} rather than into strength"
                if support
                else "an entry level you are willing to average at",
            ],
            invalidated_if=[stop_line],
            reference_levels=levels,
        )

    if label is RecommendationLabel.BUY:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.MAINTAIN,
            rationale=(
                f"A buy stance at {confidence:.0f} confidence supports keeping the "
                "position. It does not by itself argue for enlarging it."
            ),
            conditions=[f"the target at {target} remains the case being tested"]
            if target
            else [],
            invalidated_if=[stop_line],
            reference_levels=levels,
        )

    if label in (RecommendationLabel.HOLD, RecommendationLabel.WATCHLIST):
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.MAINTAIN,
            rationale=(
                f"A {label.value} stance gives no reason to change an existing "
                "position in either direction."
            ),
            conditions=["nothing in the evidence has turned"],
            invalidated_if=[stop_line, "the next analysis reaches a different stance"],
            reference_levels=levels,
        )

    if label is RecommendationLabel.REDUCE:
        return Guidance(
            position=PositionState.HOLDING,
            stance=Stance.TRIM_CANDIDATE,
            rationale=(
                "The evidence has weakened without turning outright negative, which "
                "is what a reduce stance describes: a smaller position, not none."
            ),
            conditions=[
                "how much to trim is a position-sizing decision this analysis cannot "
                "make for you",
            ],
            invalidated_if=["the evidence recovers and the stance moves back up"],
            reference_levels=levels,
        )

    return Guidance(
        position=PositionState.HOLDING,
        stance=Stance.EXIT_CANDIDATE,
        rationale=(
            f"A sell stance at {confidence:.0f} confidence describes evidence pointing "
            "down, which makes closing the position the candidate reading."
        ),
        conditions=["timing and tax consequences are yours, and are not modelled here"],
        invalidated_if=["the analysis turns, which would be a different stance entirely"],
        reference_levels=levels,
    )


def build_strategy(
    label: RecommendationLabel | str,
    confidence: float,
    *,
    support_level: Decimal | None = None,
    resistance_level: Decimal | None = None,
    target_price: Decimal | None = None,
    suggested_stop: Decimal | None = None,
) -> StrategyView:
    """Both readings of one stored recommendation."""
    resolved = label if isinstance(label, RecommendationLabel) else RecommendationLabel(label)
    levels = _levels(support_level, resistance_level, target_price, suggested_stop)

    return StrategyView(
        label=resolved,
        confidence=confidence,
        not_holding=_not_holding(resolved, confidence, levels),
        holding=_holding(resolved, confidence, levels),
        disclaimer=STRATEGY_DISCLAIMER,
    )
