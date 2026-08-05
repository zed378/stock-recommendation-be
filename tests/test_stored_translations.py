"""Both languages produced once, during the analysis, and stored.

The reader is already waiting for the analysis; doing the rendering then costs
a few seconds on a request that was going to be slow anyway and removes the
wait from every later view.

The property that matters most is the failure case. The analysis is the
product and the translation is a convenience, so a rendering step must never be
able to throw away a completed multi-agent run. Everything else here follows
from that: the original stays authoritative and identifiable, a failure leaves
it untouched, and the on-demand endpoint remains as the slower fallback.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from aidss.db.models import AnalysisResult, InvestmentHorizon, Recommendation
from aidss.domain.types import RecommendationLabel
from aidss.llm.cost import Usage
from aidss.llm.errors import AllProvidersFailedError
from aidss.llm.gateway import LLMResponse
from aidss.prompts.language import OutputLanguage
from aidss.recommendations.rendering import other_language, prose_of, render_translation

TRANSLATED = {
    "reasoning": "The medium-term trend is still up.",
    "supporting_factors": ["Price above the 50-day average"],
    "conflicting_factors": ["Volume is declining"],
    "risk_factors": ["A false breakout"],
    "bullish_scenario": "A break above resistance.",
    "bearish_scenario": "A drop below support.",
}


class FakeGateway:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.calls = 0

    def complete(self, request):  # noqa: ANN001
        self.calls += 1
        if isinstance(self._payload, Exception):
            raise self._payload
        import json

        return LLMResponse(
            content=json.dumps(self._payload, ensure_ascii=False),
            usage=Usage(
                provider="fake",
                model="translator",
                prompt_tokens=1,
                completion_tokens=1,
                cost_estimate=Decimal("0"),
            ),
        )


@pytest.fixture
def stored(session):
    from aidss.db.models import Asset

    asset = Asset(ticker="BBCA", exchange="IDX")
    session.add(asset)
    session.flush()

    result = AnalysisResult(asset_id=asset.id, analysis_type="technical")
    session.add(result)
    session.flush()

    row = Recommendation(
        analysis_result_id=result.id,
        label=RecommendationLabel.HOLD,
        confidence=72.0,
        reasoning="Tren jangka menengah masih naik.",
        supporting_factors=["Harga di atas SMA 50"],
        conflicting_factors=["Volume menurun"],
        risk_factors=["Breakout palsu"],
        bullish_scenario="Menembus resistance.",
        bearish_scenario="Jatuh di bawah support.",
        horizon=InvestmentHorizon.MEDIUM,
        # Stated, not inherited. The column has no default any more,
        # precisely so a writer that forgets fails here rather than
        # storing a row nobody can tell apart from a correct one.
        language="id",
    )
    session.add(row)
    session.flush()
    return row


# --- what is stored --------------------------------------------------------


def test_a_new_recommendation_starts_with_no_rendering(stored) -> None:
    assert stored.language == "id"
    assert stored.translations == {}


def test_the_translation_is_stored_under_its_language(session, stored) -> None:
    assert render_translation(session, FakeGateway(TRANSLATED), stored.id) is True

    session.expire_all()
    row = session.get(Recommendation, stored.id)
    assert set(row.translations) == {"en"}
    assert row.translations["en"]["fields"]["reasoning"] == TRANSLATED["reasoning"]


def test_the_original_is_untouched(session, stored) -> None:
    """The prose columns hold the text that passed schema validation and the
    execution-language guard. A rendering must not overwrite it."""
    render_translation(session, FakeGateway(TRANSLATED), stored.id)

    session.expire_all()
    row = session.get(Recommendation, stored.id)
    assert row.reasoning == "Tren jangka menengah masih naik."
    assert row.language == "id"


def test_the_rendering_is_marked_as_machine_produced(session, stored) -> None:
    """The interface must not be able to show it without knowing what it is."""
    render_translation(session, FakeGateway(TRANSLATED), stored.id)

    session.expire_all()
    entry = session.get(Recommendation, stored.id).translations["en"]
    assert entry["is_machine_translation"] is True
    assert entry["model"] == "translator"
    assert entry["translated_at"]


def test_no_stance_or_price_is_duplicated_into_the_rendering(session, stored) -> None:
    """The whole reason this is a translation rather than a second analysis:
    the two cannot disagree about what was concluded, only about the words."""
    render_translation(session, FakeGateway(TRANSLATED), stored.id)

    session.expire_all()
    fields = session.get(Recommendation, stored.id).translations["en"]["fields"]
    for key in ("label", "confidence", "target_price", "support_level", "horizon"):
        assert key not in fields


def test_only_prose_is_sent_to_be_translated(stored) -> None:
    fields = prose_of(stored)
    assert set(fields) == {
        "reasoning",
        "supporting_factors",
        "conflicting_factors",
        "risk_factors",
        "bullish_scenario",
        "bearish_scenario",
    }


# --- the failure case ------------------------------------------------------


def test_a_gateway_failure_does_not_raise(session, stored) -> None:
    """The analysis is the product. A rendering step must not be able to throw
    away a completed multi-agent run."""
    failing = FakeGateway(AllProvidersFailedError({"a": "timeout"}))
    assert render_translation(session, failing, stored.id) is False


def test_a_failure_leaves_the_recommendation_intact(session, stored) -> None:
    render_translation(session, FakeGateway(AllProvidersFailedError({"a": "down"})), stored.id)

    session.expire_all()
    row = session.get(Recommendation, stored.id)
    assert row.reasoning == "Tren jangka menengah masih naik."
    assert row.translations == {}


def test_a_partial_translation_is_not_stored(session, stored) -> None:
    """Half an analysis reads as a whole one missing its counter-evidence, so
    storing it would be worse than storing nothing."""
    assert render_translation(session, FakeGateway({"reasoning": "x"}), stored.id) is False

    session.expire_all()
    assert session.get(Recommendation, stored.id).translations == {}


def test_a_translation_bearing_an_instruction_is_not_stored(session, stored) -> None:
    """The execution-language guard runs on the rendering too."""
    bad = {**TRANSLATED, "reasoning": "Buy now while the trend is up."}
    assert render_translation(session, FakeGateway(bad), stored.id) is False

    session.expire_all()
    assert session.get(Recommendation, stored.id).translations == {}


def test_a_missing_recommendation_is_not_an_error(session) -> None:
    assert render_translation(session, FakeGateway(TRANSLATED), uuid.uuid4()) is False


# --- which language ---------------------------------------------------------


def test_the_target_is_the_one_the_reader_does_not_have() -> None:
    assert other_language("id") is OutputLanguage.EN
    assert other_language("en") is OutputLanguage.ID


def test_translating_into_the_original_language_is_a_no_op(session, stored) -> None:
    """Paying a model to render Indonesian as Indonesian buys nothing."""
    gateway = FakeGateway(TRANSLATED)
    assert render_translation(session, gateway, stored.id, target=OutputLanguage.ID) is False
    assert gateway.calls == 0


def test_a_second_language_does_not_replace_the_first(session, stored) -> None:
    """The column is a map, so a third language costs a key rather than a
    migration and six more columns."""
    render_translation(session, FakeGateway(TRANSLATED), stored.id)
    session.expire_all()

    row = session.get(Recommendation, stored.id)
    row.language = "en"
    session.flush()
    render_translation(session, FakeGateway({"reasoning": "kembali", **{
        k: v for k, v in TRANSLATED.items() if k != "reasoning"
    }}), stored.id)

    session.expire_all()
    assert set(session.get(Recommendation, stored.id).translations) == {"en", "id"}
