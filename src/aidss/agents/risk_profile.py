"""Deriving an investor's risk profile from what they answer, not what they claim.

The profile screen asks directly: conservative, moderate, or aggressive. That is
the cheapest possible instrument and the least reliable one, because the
question invites an answer about self-image rather than behaviour. People who
describe themselves as aggressive sell at the first drawdown, and people who
call themselves conservative hold through one without noticing.

So this asks about situations instead, and derives the label. The answers are
kept alongside the result: a derivation nobody can inspect is a number the
reader has to take on faith, and one that cannot be re-run is frozen the day
the scoring changes.

**Two dimensions, and the lower one wins.**

  * *Tolerance* is willingness - what a drawdown does to your sleep.
  * *Capacity* is ability - whether you could absorb the loss if it happened.

A reader who is willing but unable is not aggressive, they are exposed. Taking
the minimum is the standard reading and the only defensible one: no amount of
enthusiasm makes rent money into risk capital.

**This is not a suitability assessment and the platform must not present it as
one.** It changes how analysis is written - what gets emphasised, how fully the
downside is spelled out - and never what the analysis concludes. The stance,
the levels and the confidence are properties of the evidence. A platform that
told the cautious reader to sell and the bold one to buy would not be adapting
to them, it would be agreeing with them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Dimension(StrEnum):
    #: Willingness to sit through a loss.
    TOLERANCE = "tolerance"
    #: Ability to absorb one.
    CAPACITY = "capacity"
    #: Not scored - read directly for the investment horizon.
    HORIZON = "horizon"
    #: Neither dimension held the result back; they agreed. Reported rather
    #: than defaulting to one of the two, so the interface can say "both point
    #: the same way" instead of naming a constraint that did not bind.
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    #: 0 is the most cautious answer, 3 the boldest. Kept small and integral so
    #: the arithmetic is inspectable: a reader who disagrees with the outcome
    #: can see exactly which answer moved it.
    points: int


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    dimension: Dimension
    options: tuple[Option, ...]

    def points_for(self, answer: str) -> int | None:
        for option in self.options:
            if option.key == answer:
                return option.points
        return None


#: The instrument. Deliberately short - a questionnaire nobody finishes
#: measures nothing - and deliberately behavioural.
#:
#: Prose lives in the interface's message table rather than here, so the
#: questions can be reworded in either language without touching the scoring.
QUESTIONS: tuple[Question, ...] = (
    Question(
        key="drawdown_reaction",
        dimension=Dimension.TOLERANCE,
        # The single most diagnostic question in any risk instrument, because
        # it describes an event rather than a preference.
        options=(
            Option("sell_all", 0),
            Option("sell_some", 1),
            Option("hold", 2),
            Option("buy_more", 3),
        ),
    ),
    Question(
        key="volatility_preference",
        dimension=Dimension.TOLERANCE,
        options=(
            Option("stable_low", 0),
            Option("mild_swings", 1),
            Option("meaningful_swings", 2),
            Option("large_swings", 3),
        ),
    ),
    Question(
        key="past_loss_experience",
        dimension=Dimension.TOLERANCE,
        # Asked as a fact about the past, not a prediction about the future.
        options=(
            Option("never_invested", 0),
            Option("lost_and_stopped", 0),
            Option("lost_and_continued", 2),
            Option("lost_and_added", 3),
        ),
    ),
    Question(
        key="share_of_savings",
        dimension=Dimension.CAPACITY,
        options=(
            Option("most_of_it", 0),
            Option("about_half", 1),
            Option("a_quarter", 2),
            Option("small_share", 3),
        ),
    ),
    Question(
        key="emergency_fund",
        dimension=Dimension.CAPACITY,
        # The question that most often lowers a profile, and the reason the two
        # dimensions are separate: somebody with no buffer is forced to sell
        # into a fall regardless of how they feel about it.
        options=(
            Option("none", 0),
            Option("under_three_months", 1),
            Option("three_to_six_months", 2),
            Option("over_six_months", 3),
        ),
    ),
    Question(
        key="income_stability",
        dimension=Dimension.CAPACITY,
        options=(
            Option("irregular", 0),
            Option("somewhat_variable", 1),
            Option("stable", 2),
            Option("stable_and_growing", 3),
        ),
    ),
    Question(
        key="time_until_needed",
        dimension=Dimension.HORIZON,
        # Read for the horizon, and also capped against capacity below: money
        # needed inside a year cannot sit in a volatile position however
        # comfortable its owner is.
        options=(
            Option("under_a_year", 0),
            Option("one_to_three_years", 1),
            Option("three_to_seven_years", 2),
            Option("over_seven_years", 3),
        ),
    ),
)

BY_KEY = {question.key: question for question in QUESTIONS}

_APPETITE_ORDER = ("conservative", "moderate", "aggressive")
_HORIZON_BY_POINTS = {0: "short", 1: "short", 2: "medium", 3: "long"}


class IncompleteAnswers(ValueError):
    """Not every question was answered, or an answer was not on the list."""


@dataclass(frozen=True, slots=True)
class RiskProfile:
    """A derived profile, with everything needed to argue with it."""

    risk_appetite: str
    investment_horizon: str
    tolerance_score: int
    capacity_score: int
    #: Which of the two produced the final label. Reported because "you
    #: answered boldly but have no buffer" is the useful sentence, and a bare
    #: label cannot say it.
    limited_by: Dimension
    answers: dict[str, str]

    def as_payload(self) -> dict[str, Any]:
        return {
            "risk_appetite": self.risk_appetite,
            "investment_horizon": self.investment_horizon,
            "tolerance_score": self.tolerance_score,
            "capacity_score": self.capacity_score,
            "limited_by": self.limited_by.value,
            "answers": dict(self.answers),
        }


def _band(score: int, out_of: int) -> int:
    """Score to a 0-2 band. Thresholds at a third and two thirds."""
    if out_of <= 0:
        return 0
    share = score / out_of
    if share < 1 / 3:
        return 0
    if share < 2 / 3:
        return 1
    return 2


def derive(answers: dict[str, str]) -> RiskProfile:
    """Turn a full set of answers into a profile.

    Refuses a partial set rather than scoring what is there. A missing answer
    is not a cautious answer, and treating it as zero would quietly mark
    somebody conservative for skipping a question they found unclear.
    """
    missing = [question.key for question in QUESTIONS if question.key not in answers]
    if missing:
        raise IncompleteAnswers(f"unanswered: {', '.join(sorted(missing))}")

    scores: dict[Dimension, int] = {Dimension.TOLERANCE: 0, Dimension.CAPACITY: 0}
    maxima: dict[Dimension, int] = {Dimension.TOLERANCE: 0, Dimension.CAPACITY: 0}
    horizon_points = 0

    for question in QUESTIONS:
        points = question.points_for(answers[question.key])
        if points is None:
            raise IncompleteAnswers(
                f"{answers[question.key]!r} is not an option for {question.key!r}"
            )
        if question.dimension is Dimension.HORIZON:
            horizon_points = points
            continue
        scores[question.dimension] += points
        maxima[question.dimension] += max(option.points for option in question.options)

    tolerance = _band(scores[Dimension.TOLERANCE], maxima[Dimension.TOLERANCE])
    capacity = _band(scores[Dimension.CAPACITY], maxima[Dimension.CAPACITY])

    # Money needed inside a year is not risk capital, whatever the buffer looks
    # like. Folded into capacity rather than handled separately, because it is
    # the same question: could you absorb the loss if it happened before you
    # needed the money.
    if horizon_points == 0:
        capacity = 0

    if capacity == tolerance:
        limited_by = Dimension.NEITHER
    else:
        limited_by = Dimension.CAPACITY if capacity < tolerance else Dimension.TOLERANCE

    return RiskProfile(
        risk_appetite=_APPETITE_ORDER[min(tolerance, capacity)],
        investment_horizon=_HORIZON_BY_POINTS[horizon_points],
        tolerance_score=scores[Dimension.TOLERANCE],
        capacity_score=scores[Dimension.CAPACITY],
        limited_by=limited_by,
        answers=dict(answers),
    )
