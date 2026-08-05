"""One stance, read from both sides of a position.

The behaviour worth pinning is the asymmetry. A `hold` on something you own and
a `hold` on something you do not are the same word describing two different
situations, and a screen that collapsed them would answer only one of the two
questions people actually have.

The second thing pinned here is the wording. Section 5.4 puts recommendation
labels under a rule - a stance, never a command - and guidance derived from
them inherits it. These tests fail if a phrasing ever drifts into an
instruction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aidss.domain.types import RecommendationLabel
from aidss.recommendations.strategy import (
    ENTRY_CONFIDENCE_FLOOR,
    PositionState,
    Stance,
    build_strategy,
)

LEVELS = {
    "support_level": Decimal("9000"),
    "resistance_level": Decimal("10500"),
    "target_price": Decimal("11000"),
    "suggested_stop": Decimal("8700"),
}


def view(label: RecommendationLabel, confidence: float = 80.0, **overrides):
    return build_strategy(label, confidence, **{**LEVELS, **overrides})


# --- the asymmetry ---------------------------------------------------------


def test_hold_means_stay_put_from_both_sides_and_they_differ() -> None:
    """The case that motivated the whole module.

    Someone holding should keep; someone not holding has no reason to start.
    One label, two readings.
    """
    result = view(RecommendationLabel.HOLD)
    assert result.holding.stance is Stance.MAINTAIN
    assert result.not_holding.stance is Stance.NO_ENTRY_BASIS


def test_a_sell_is_an_exit_for_a_holder_and_an_avoid_for_everyone_else() -> None:
    result = view(RecommendationLabel.SELL)
    assert result.holding.stance is Stance.EXIT_CANDIDATE
    assert result.not_holding.stance is Stance.AVOID


def test_a_reduce_trims_rather_than_exits() -> None:
    """Reduce describes a smaller position, not none - and collapsing it into
    sell would turn a shade of opinion into a decision."""
    assert view(RecommendationLabel.REDUCE).holding.stance is Stance.TRIM_CANDIDATE


def test_a_strong_buy_lets_a_holder_add_but_a_plain_buy_does_not() -> None:
    """A buy supports keeping a position; it does not by itself argue for
    enlarging one, and treating the two the same would quietly concentrate."""
    assert view(RecommendationLabel.STRONG_BUY).holding.stance is Stance.ACCUMULATE_CANDIDATE
    assert view(RecommendationLabel.BUY).holding.stance is Stance.MAINTAIN


def test_watchlist_is_a_wait_for_a_non_holder_and_a_keep_for_a_holder() -> None:
    result = view(RecommendationLabel.WATCHLIST)
    assert result.not_holding.stance is Stance.WAIT_FOR_LEVEL
    assert result.holding.stance is Stance.MAINTAIN


def test_both_readings_are_always_returned() -> None:
    """Seeing the case you are not in is what makes the asymmetry visible."""
    result = view(RecommendationLabel.BUY)
    assert result.not_holding.position is PositionState.NOT_HOLDING
    assert result.holding.position is PositionState.HOLDING


# --- confidence gates entry, not maintenance -------------------------------


def test_a_buy_on_thin_evidence_becomes_wait_rather_than_enter() -> None:
    """Section 5.4 already refuses a strong label on thin evidence. Acting on a
    weak one is the same mistake one step later."""
    result = view(RecommendationLabel.BUY, confidence=ENTRY_CONFIDENCE_FLOOR - 1)
    assert result.not_holding.stance is Stance.WAIT_FOR_LEVEL
    assert "confidence" in result.not_holding.rationale.lower()


def test_thin_evidence_does_not_force_a_holder_out() -> None:
    """Low confidence in a buy is a reason not to start, not a reason to leave.
    Treating it as both would churn a position on an unchanged view."""
    result = view(RecommendationLabel.BUY, confidence=ENTRY_CONFIDENCE_FLOOR - 1)
    assert result.holding.stance is Stance.MAINTAIN


def test_sufficient_confidence_makes_a_buy_an_entry_candidate() -> None:
    result = view(RecommendationLabel.BUY, confidence=ENTRY_CONFIDENCE_FLOOR + 1)
    assert result.not_holding.stance is Stance.ENTRY_CANDIDATE


# --- every stance can be shown to have been wrong --------------------------


@pytest.mark.parametrize("label", list(RecommendationLabel))
def test_every_stance_states_what_would_invalidate_it(label: RecommendationLabel) -> None:
    """A stance with no stated invalidation can never be shown to have been
    mistaken, and those are the ones people hold on to longest."""
    result = view(label)
    assert result.holding.invalidated_if, f"{label.value} holding has no invalidation"
    assert result.not_holding.invalidated_if, f"{label.value} not-holding has no invalidation"


def test_the_stop_level_is_what_invalidates_a_holding_when_there_is_one() -> None:
    result = view(RecommendationLabel.BUY)
    assert any("8,700" in line for line in result.holding.invalidated_if)


def test_a_missing_level_still_produces_an_invalidation() -> None:
    """No stored levels is common on a thin history, and a stance with no exit
    condition is worse than one with a vague exit condition."""
    result = build_strategy(RecommendationLabel.BUY, 80.0)
    assert result.holding.invalidated_if
    assert result.not_holding.invalidated_if


# --- wording stays a stance, never an order --------------------------------


FORBIDDEN = (
    "buy now",
    "sell now",
    "place an order",
    "you should buy",
    "you should sell",
    "execute",
    "we recommend buying",
    "we recommend selling",
)


@pytest.mark.parametrize("label", list(RecommendationLabel))
def test_no_guidance_reads_as_an_instruction(label: RecommendationLabel) -> None:
    """Section 5.4 applies to derived text as much as to the labels."""
    result = view(label)
    blob = " ".join(
        [
            result.holding.rationale,
            result.not_holding.rationale,
            *result.holding.conditions,
            *result.not_holding.conditions,
            *result.holding.invalidated_if,
            *result.not_holding.invalidated_if,
        ]
    ).lower()
    for phrase in FORBIDDEN:
        assert phrase not in blob, f"{label.value} guidance reads as an instruction: {phrase}"


@pytest.mark.parametrize("label", list(RecommendationLabel))
def test_no_stance_name_is_an_imperative(label: RecommendationLabel) -> None:
    """`entry_candidate`, not `enter`. The naming is the distinction."""
    result = view(label)
    for stance in (result.holding.stance, result.not_holding.stance):
        assert stance.value not in {"buy", "sell", "enter", "exit", "trim", "add"}


def test_the_disclaimer_states_the_execution_limit() -> None:
    text = view(RecommendationLabel.BUY).disclaimer.lower()
    assert "not investment advice" in text
    assert "places no orders" in text


# --- position sizing is never assumed --------------------------------------


def test_sizing_is_named_as_the_readers_decision_where_it_matters() -> None:
    """The analysis knows nothing about the reader's other positions, and a
    stance that implied a size would be pretending otherwise."""
    entry = view(RecommendationLabel.BUY).not_holding
    trim = view(RecommendationLabel.REDUCE).holding
    assert any("size" in c.lower() or "concentration" in c.lower() for c in entry.conditions)
    assert any("position-sizing" in c.lower() or "size" in c.lower() for c in trim.conditions)


def test_levels_are_carried_through_for_both_sides() -> None:
    result = view(RecommendationLabel.BUY)
    assert result.holding.reference_levels["support"] == "9,000.00"
    assert result.not_holding.reference_levels["resistance"] == "10,500.00"


def test_a_string_label_is_accepted() -> None:
    """The stored column is an enum, but callers reading JSON have a string."""
    assert build_strategy("buy", 80.0).label is RecommendationLabel.BUY


# --- both languages, built the same way ------------------------------------


#: Named apart from the `LEVELS` at the top of this file. Appending a second
#: constant with the same name rebound it for every test above, which changed
#: what they were asserting against without touching a line of them.
ALL_LEVELS = dict(
    support_level=Decimal("6362.5"),
    resistance_level=Decimal("6550"),
    target_price=Decimal("7000"),
    suggested_stop=Decimal("6000"),
)


@pytest.mark.parametrize("label", list(RecommendationLabel))
@pytest.mark.parametrize("confidence", [40.0, 85.0])
@pytest.mark.parametrize("levels", [{}, ALL_LEVELS], ids=["no-levels", "all-levels"])
def test_every_branch_renders_in_every_language(label, confidence, levels) -> None:
    """A phrase table with a gap fails only on the branch that reaches it, and
    only in one language - which is exactly the kind of hole that ships. This
    walks every branch in every language instead of trusting the table."""
    from aidss.recommendations.strategy import STRATEGY_LANGUAGES

    view = build_strategy(label, confidence, **levels)

    assert set(view.translations) == set(STRATEGY_LANGUAGES) - {"en"}
    for language in view.translations:
        rendered = view.translations[language]
        for side in ("not_holding", "holding"):
            assert rendered[side]["rationale"].strip()
            # Never empty by construction: a stance with no stated invalidation
            # is one that can never be shown to have been mistaken.
            assert rendered[side]["invalidated_if"]


@pytest.mark.parametrize("label", list(RecommendationLabel))
def test_the_languages_describe_the_same_stance(label) -> None:
    """Two walks of one decision tree, not two opinions. If the phrase table
    ever drifted into changing which branch is taken, the stances would part
    company and the reader would have no way to resolve it."""
    view = build_strategy(label, 85.0, **ALL_LEVELS)

    for rendered in view.translations.values():
        assert rendered["not_holding"]["stance"] == view.not_holding.stance.value
        assert rendered["holding"]["stance"] == view.holding.stance.value
        assert rendered["not_holding"]["reference_levels"] == view.not_holding.reference_levels


@pytest.mark.parametrize("label", list(RecommendationLabel))
def test_no_language_leaves_a_placeholder_unfilled(label) -> None:
    """A template whose parameter was never passed renders the braces
    literally, which looks like a typo rather than the missing value it is."""
    view = build_strategy(label, 85.0, **ALL_LEVELS)

    texts = []
    for rendered in (
        view.not_holding.as_dict(),
        view.holding.as_dict(),
        *(
            side
            for language in view.translations.values()
            for side in (language["not_holding"], language["holding"])
        ),
    ):
        texts.append(rendered["rationale"])
        texts.extend(rendered["conditions"])
        texts.extend(rendered["invalidated_if"])

    for text in texts:
        assert "{" not in text and "}" not in text, text


def test_the_indonesian_text_is_not_the_english_text() -> None:
    """Both are written by hand. If one were ever accidentally copied from the
    other, the switch would appear to work and change nothing."""
    view = build_strategy(RecommendationLabel.WATCHLIST, 85.0, **ALL_LEVELS)
    assert view.translations["id"]["not_holding"]["rationale"] != view.not_holding.rationale
    assert view.translations["id"]["disclaimer"] != view.disclaimer
