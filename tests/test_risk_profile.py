"""Deriving a risk profile from answers rather than asking for the label.

The behaviour that matters is the one that surprises people: willingness and
ability are scored separately and the *lower* one decides. Somebody who answers
every tolerance question boldly and has no emergency fund is not aggressive,
they are exposed, and no amount of enthusiasm turns rent money into risk
capital.
"""

from __future__ import annotations

import pytest

from aidss.agents.risk_profile import (
    QUESTIONS,
    Dimension,
    IncompleteAnswers,
    derive,
)

BOLD = {question.key: question.options[-1].key for question in QUESTIONS}
TIMID = {question.key: question.options[0].key for question in QUESTIONS}


def answering(**overrides: str) -> dict[str, str]:
    return {**BOLD, **overrides}


def test_every_bold_answer_gives_the_bold_profile() -> None:
    profile = derive(BOLD)

    assert profile.risk_appetite == "aggressive"
    assert profile.investment_horizon == "long"


def test_every_cautious_answer_gives_the_cautious_profile() -> None:
    profile = derive(TIMID)

    assert profile.risk_appetite == "conservative"
    assert profile.investment_horizon == "short"


def test_willingness_without_ability_is_not_aggressive() -> None:
    """The whole reason the two dimensions are separate. This reader answered
    every tolerance question at the top of the scale and has no buffer, no
    stable income, and everything they own in the market."""
    profile = derive(
        answering(
            emergency_fund="none",
            income_stability="irregular",
            share_of_savings="most_of_it",
        )
    )

    assert profile.risk_appetite == "conservative"
    assert profile.tolerance_score == 9
    assert profile.capacity_score == 0
    assert profile.limited_by is Dimension.CAPACITY


def test_ability_without_willingness_is_not_aggressive_either() -> None:
    """A portfolio that costs its owner sleep gets sold at the worst possible
    moment, so capacity does not override a stated unwillingness."""
    profile = derive(
        {
            **BOLD,
            "drawdown_reaction": "sell_all",
            "volatility_preference": "stable_low",
            "past_loss_experience": "lost_and_stopped",
        }
    )

    assert profile.risk_appetite == "conservative"
    assert profile.limited_by is Dimension.TOLERANCE


def test_money_needed_within_a_year_is_never_risk_capital() -> None:
    """Regardless of buffer, income or temperament. The horizon question is
    read for the horizon and also caps capacity, because it is the same
    question: could you absorb the loss before you needed the money."""
    profile = derive(answering(time_until_needed="under_a_year"))

    assert profile.risk_appetite == "conservative"
    assert profile.investment_horizon == "short"


def test_agreement_names_neither_dimension() -> None:
    """Reporting "limited by capacity" when nothing limited it would put a
    constraint in the interface's sentence that did not bind."""
    assert derive(BOLD).limited_by is Dimension.NEITHER
    assert derive(TIMID).limited_by is Dimension.NEITHER


def test_a_missing_answer_is_refused_rather_than_scored() -> None:
    """A skipped question is not a cautious answer. Scored as zero it would
    quietly mark somebody conservative for finding a question unclear."""
    partial = dict(BOLD)
    partial.pop("emergency_fund")

    with pytest.raises(IncompleteAnswers, match="emergency_fund"):
        derive(partial)


def test_an_answer_that_is_not_on_the_list_is_refused() -> None:
    with pytest.raises(IncompleteAnswers):
        derive({**BOLD, "drawdown_reaction": "panic_and_email_support"})


def test_the_answers_are_kept_with_the_result() -> None:
    """A derivation nobody can inspect is a label the reader has to take on
    faith, and one that cannot be re-run is frozen the day the scoring
    changes."""
    profile = derive(BOLD)

    assert profile.answers == BOLD


def test_the_scoring_is_monotone_in_every_tolerance_question() -> None:
    """A bolder answer must never lower the tolerance score. Written as a sweep
    rather than a spot check, because the failure it guards - one option's
    points out of order - looks entirely reasonable in the source."""
    for question in QUESTIONS:
        if question.dimension is not Dimension.TOLERANCE:
            continue
        scores = [
            derive({**TIMID, question.key: option.key}).tolerance_score
            for option in question.options
        ]
        assert scores == sorted(scores), f"{question.key} is not monotone"


def test_no_question_is_orphaned_from_a_dimension() -> None:
    """A question scored into no dimension is one the reader answers for
    nothing."""
    for question in QUESTIONS:
        assert question.dimension in set(Dimension)
        assert len(question.options) >= 2


# --- the endpoints ----------------------------------------------------------


def test_the_questions_are_served_without_wording(client, auth_headers) -> None:
    """Keys only. The prose lives in the interface's message table so a
    question can be reworded in either language without touching the scoring
    that produced somebody's stored profile."""
    body = client.get("/me/risk-profile/questions", headers=auth_headers).json()

    assert len(body["questions"]) == len(QUESTIONS)
    assert all("options" in question for question in body["questions"])
    assert "not a suitability assessment" in body["caveat"]


def test_nothing_taken_yet_returns_null(client, auth_headers) -> None:
    assert client.get("/me/risk-profile", headers=auth_headers).json() is None


def test_submitting_sets_the_preferences_the_prompts_read(client, auth_headers) -> None:
    """The point of the feature: the screening has to reach the framing, or it
    is a questionnaire that changes nothing."""
    client.post("/me/risk-profile", headers=auth_headers, json={"answers": TIMID})

    preferences = client.get("/me/preferences", headers=auth_headers).json()
    assert preferences["risk_appetite"] == "conservative"
    assert preferences["investment_horizon"] == "short"


def test_a_derived_preference_is_not_reported_as_stated(client, auth_headers) -> None:
    """The investor answered the questions; they did not state the label. An
    inference reflected back as "you told us" is how a product starts being
    confidently wrong about people."""
    client.post("/me/risk-profile", headers=auth_headers, json={"answers": BOLD})

    stated = client.get("/me/preferences", headers=auth_headers).json()["stated"]
    assert "risk_answers" in stated
    assert "risk_appetite" not in stated


def test_a_hand_set_appetite_is_not_overruled_by_the_questionnaire(
    client, auth_headers
) -> None:
    """The Memory Manager keeps a stated preference above a derived one, so
    somebody who disagrees with their screening can say so and have it stick."""
    client.patch(
        "/me/preferences", headers=auth_headers, json={"risk_appetite": "aggressive"}
    )
    client.post("/me/risk-profile", headers=auth_headers, json={"answers": TIMID})

    assert (
        client.get("/me/preferences", headers=auth_headers).json()["risk_appetite"]
        == "aggressive"
    )


def test_an_incomplete_submission_is_refused(client, auth_headers) -> None:
    partial = dict(BOLD)
    partial.pop("income_stability")

    response = client.post(
        "/me/risk-profile", headers=auth_headers, json={"answers": partial}
    )

    assert response.status_code == 422


def test_the_stored_screening_reads_back(client, auth_headers) -> None:
    client.post("/me/risk-profile", headers=auth_headers, json={"answers": BOLD})

    body = client.get("/me/risk-profile", headers=auth_headers).json()

    assert body["risk_appetite"] == "aggressive"
    assert body["answers"] == BOLD
