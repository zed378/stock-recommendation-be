"""The investor profile, and the one thing it must never do.

Framing changes emphasis, ordering, and how much gets explained. It must not
change the stance, the levels, or the confidence: two investors looking at the
same issuer on the same day are looking at the same facts, and a platform that
told the cautious one to sell and the aggressive one to buy would not be
personalising, it would be telling each of them what they wanted to hear.
"""

from __future__ import annotations

from aidss.agents.memory import MemoryManager, PreferenceKey
from aidss.prompts.framing import investor_framing

#: Whatever the technical template interpolates. Values are irrelevant here -
#: the system message is what these tests read, and the user message only has
#: to render without raising.
VARIABLES = {
    "ticker": "BBRI",
    "exchange": "IDX",
    "timeframe": "1d",
    "as_of": "2026-08-08",
    "indicators": {},
    "features": {},
    "breakout": {},
    "structure": "none",
    "support": [],
    "resistance": [],
}


def test_nothing_known_produces_no_framing() -> None:
    """Empty rather than a default paragraph. A profile nobody stated must not
    produce instructions that read as though they did - the Memory Manager's
    defaults exist so code has something to read, not so the model is told the
    investor asked for something."""
    assert investor_framing(None) == ""
    assert investor_framing({}) == ""


def test_an_unrecognised_value_produces_no_framing() -> None:
    """A value outside the closed set matches no entry in the framing table.
    Silence is right; inventing a sentence for it would be worse."""
    assert investor_framing({"investment_horizon": "quarterly"}) == ""


def test_the_horizon_reaches_the_prompt() -> None:
    block = investor_framing({"investment_horizon": "long"})

    assert "years" in block


def test_the_framing_forbids_changing_the_conclusion() -> None:
    """The load-bearing sentence. Without it the model is handed a risk
    appetite and no instruction about what not to do with it."""
    block = investor_framing({"risk_appetite": "aggressive"})

    assert "must" in block.lower()
    assert "conclusion" in block.lower()
    assert "never soften a risk" in block.lower()


def test_no_profile_asks_for_a_different_stance() -> None:
    """Read across every combination: nothing in the framing table may contain
    language that pushes toward or away from a recommendation label."""
    for horizon in ("short", "medium", "long"):
        for risk in ("conservative", "moderate", "aggressive"):
            for level in ("beginner", "intermediate", "advanced"):
                block = investor_framing(
                    {
                        "investment_horizon": horizon,
                        "risk_appetite": risk,
                        "experience_level": level,
                    }
                ).lower()
                for word in (" buy", " sell", "recommend", "avoid this"):
                    assert word not in block, f"{horizon}/{risk}/{level} leaks a stance"


def test_the_composer_appends_the_framing(session) -> None:
    """The reason this module exists. The profile reached the prompt variables
    for a long time and no template ever interpolated it, so every analysis was
    written for the defaults."""
    from aidss.prompts.manager import PromptComposer
    from aidss.prompts.schemas import TechnicalOutput

    composer = PromptComposer()
    prompt = composer.compose(
        "technical_analysis",
        VARIABLES,
        TechnicalOutput,
        investor={"investment_horizon": "long", "risk_appetite": "conservative"},
    )

    system = prompt.messages[0].content
    assert "WHO IS READING THIS" in system
    assert "years" in system


def test_the_composer_without_a_profile_is_unchanged(session) -> None:
    from aidss.prompts.manager import PromptComposer
    from aidss.prompts.schemas import TechnicalOutput

    composer = PromptComposer()
    plain = composer.compose("technical_analysis", VARIABLES, TechnicalOutput)
    empty = composer.compose(
        "technical_analysis", VARIABLES, TechnicalOutput, investor={}
    )

    assert plain.messages[0].content == empty.messages[0].content


# --- the endpoint -----------------------------------------------------------


def test_preferences_start_at_their_defaults(client, auth_headers) -> None:
    body = client.get("/me/preferences", headers=auth_headers).json()

    assert body["investment_horizon"] == "medium"
    assert body["stated"] == [], "nothing has been said yet"


def test_setting_one_preference_leaves_the_others(client, auth_headers) -> None:
    """Partial for the same reason the provider PATCH is: a form that saves one
    field must not quietly reset the four beside it."""
    client.patch(
        "/me/preferences", headers=auth_headers, json={"risk_appetite": "conservative"}
    )
    body = client.patch(
        "/me/preferences", headers=auth_headers, json={"investment_horizon": "long"}
    ).json()

    assert body["risk_appetite"] == "conservative"
    assert body["investment_horizon"] == "long"


def test_a_stated_preference_is_reported_as_stated(client, auth_headers) -> None:
    """The distinction the Memory Manager was built around. A default reflected
    back as a choice is how a product starts being confidently wrong about
    people."""
    client.patch("/me/preferences", headers=auth_headers, json={"privacy_mode": "high"})
    body = client.get("/me/preferences", headers=auth_headers).json()

    assert "privacy_mode" in body["stated"]
    assert "risk_appetite" not in body["stated"]


def test_a_value_outside_the_set_is_refused(client, auth_headers) -> None:
    response = client.patch(
        "/me/preferences", headers=auth_headers, json={"investment_horizon": "forever"}
    )

    assert response.status_code == 422


def test_a_stale_stored_value_does_not_break_the_page(client, auth_headers, session) -> None:
    """The preference store is a JSON column with no constraint, so a value
    written by an older build can be anything. Returned as-is it fails response
    validation and turns a settings page into a 500."""
    from aidss.db.base import get_sessionmaker
    from aidss.db.models import User

    db = get_sessionmaker()()
    try:
        user = db.scalars(__import__("sqlalchemy").select(User)).first()
        MemoryManager(db).remember(user.id, PreferenceKey.HORIZON, "decades")
        db.commit()
    finally:
        db.close()

    response = client.get("/me/preferences", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["investment_horizon"] == "medium"


def test_high_privacy_still_routes_sensitively(session) -> None:
    """The one preference with a consequence beyond wording. Setting it must
    keep reaching the router, not just the prompt."""
    import uuid

    user_id = uuid.uuid4()
    manager = MemoryManager(session)
    manager.remember(user_id, PreferenceKey.PRIVACY_MODE, "high")

    assert manager.load(user_id).high_privacy is True
