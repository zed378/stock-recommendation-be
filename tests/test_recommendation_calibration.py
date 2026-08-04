"""Confidence calibration and derived price levels (Section 5.4).

Section 5.4 asks for "a consistently calibrated score, not an arbitrary number
from the LLM". These tests are what makes that claim checkable: the score is a
pure function of the evidence, and the model's own number never reaches it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aidss.domain.types import RecommendationLabel
from aidss.prompts.schemas import (
    Bias,
    DataSufficiency,
    FundamentalOutput,
    NewsSentimentOutput,
    TechnicalOutput,
)
from aidss.recommendations.calibration import (
    MAX_CONFIDENCE,
    EvidenceSignal,
    calibrate,
    compute_agreement,
    compute_balance,
    compute_coverage,
    derive_levels,
    evidence_direction,
    signals_from_agent_outputs,
)


def technical(bias: Bias, sufficiency: DataSufficiency = DataSufficiency.SUFFICIENT):
    return TechnicalOutput(
        summary="s", confidence=50.0, data_sufficiency=sufficiency, bias=bias
    )


def fundamental(bias: Bias, sufficiency: DataSufficiency = DataSufficiency.SUFFICIENT):
    return FundamentalOutput(
        summary="s", confidence=50.0, data_sufficiency=sufficiency, bias=bias
    )


def news(score: float, sufficiency: DataSufficiency = DataSufficiency.SUFFICIENT):
    return NewsSentimentOutput(
        summary="s", confidence=50.0, data_sufficiency=sufficiency, sentiment_score=score
    )


def signal(agent: str, direction: int, sufficiency=DataSufficiency.SUFFICIENT) -> EvidenceSignal:
    return EvidenceSignal(agent=agent, direction=direction, sufficiency=sufficiency)


# --- Determinism -----------------------------------------------------------


def test_calibration_is_deterministic() -> None:
    outputs = {"technical_analyzer": technical(Bias.BULLISH)}
    first = calibrate(outputs, supporting_count=3, conflicting_count=2)
    second = calibrate(outputs, supporting_count=3, conflicting_count=2)
    assert first.confidence == second.confidence


def test_the_models_own_confidence_never_reaches_the_score() -> None:
    """Section 5.4's central requirement, stated as a test.

    Two analyzer sets identical in every respect except the number the model
    reported must calibrate identically.
    """
    modest = {"technical_analyzer": technical(Bias.BULLISH)}
    modest["technical_analyzer"].confidence = 5.0

    boastful = {"technical_analyzer": technical(Bias.BULLISH)}
    boastful["technical_analyzer"].confidence = 99.0

    assert (
        calibrate(modest, supporting_count=2, conflicting_count=2).confidence
        == calibrate(boastful, supporting_count=2, conflicting_count=2).confidence
    )


# --- Coverage --------------------------------------------------------------


def test_coverage_is_partial_when_only_one_source_exists() -> None:
    """Price data alone is a thin basis, however fluent the narrative."""
    coverage = compute_coverage([signal("technical_analyzer", 1)])
    assert 0.4 < coverage < 0.5


def test_coverage_is_complete_when_every_source_is_sufficient() -> None:
    coverage = compute_coverage(
        [
            signal("technical_analyzer", 1),
            signal("fundamental_analyzer", 1),
            signal("news_analyzer", 1),
        ]
    )
    assert coverage == pytest.approx(1.0)


def test_partial_data_earns_partial_coverage() -> None:
    full = compute_coverage([signal("technical_analyzer", 1)])
    partial = compute_coverage(
        [signal("technical_analyzer", 1, DataSufficiency.PARTIAL)]
    )
    assert partial == pytest.approx(full / 2)


def test_an_insufficient_source_earns_no_coverage() -> None:
    assert compute_coverage(
        [signal("technical_analyzer", 1, DataSufficiency.INSUFFICIENT)]
    ) == pytest.approx(0.0)


# --- Agreement -------------------------------------------------------------


def test_a_lone_source_scores_half_not_full() -> None:
    """A single voice agreeing with itself is not corroboration."""
    assert compute_agreement([signal("technical_analyzer", 1)]) == 0.5


def test_unanimous_sources_score_full_agreement() -> None:
    agreement = compute_agreement(
        [signal("technical_analyzer", 1), signal("fundamental_analyzer", 1)]
    )
    assert agreement == pytest.approx(1.0)


def test_disagreeing_sources_score_lower() -> None:
    agreement = compute_agreement(
        [signal("technical_analyzer", 1), signal("fundamental_analyzer", -1)]
    )
    assert agreement == pytest.approx(0.5)


def test_a_source_with_no_data_is_not_counted_as_neutral() -> None:
    """Silence is not a third opinion diluting a genuine consensus."""
    with_silent = compute_agreement(
        [
            signal("technical_analyzer", 1),
            signal("fundamental_analyzer", 1),
            signal("news_analyzer", 0, DataSufficiency.INSUFFICIENT),
        ]
    )
    assert with_silent == pytest.approx(1.0)


def test_no_usable_source_scores_zero_agreement() -> None:
    assert compute_agreement(
        [signal("technical_analyzer", 1, DataSufficiency.INSUFFICIENT)]
    ) == 0.0


# --- Balance ---------------------------------------------------------------


def test_no_conflicting_factors_scores_zero_balance() -> None:
    """A recommendation that finds nothing against itself has not looked."""
    assert compute_balance(supporting=8, conflicting=0) == 0.0


def test_an_even_split_scores_full_balance() -> None:
    assert compute_balance(supporting=3, conflicting=3) == pytest.approx(1.0)


def test_a_healthy_imbalance_still_scores_well() -> None:
    """Some imbalance is normal; only total one-sidedness is a failure."""
    assert compute_balance(supporting=4, conflicting=2) > 0.7


def test_no_factors_at_all_scores_zero() -> None:
    assert compute_balance(supporting=0, conflicting=0) == 0.0


# --- Composite score -------------------------------------------------------


def test_thin_evidence_produces_low_confidence() -> None:
    result = calibrate(
        {"technical_analyzer": technical(Bias.BULLISH, DataSufficiency.PARTIAL)},
        supporting_count=3,
        conflicting_count=1,
    )
    assert result.confidence < 50


def test_broad_agreeing_evidence_produces_high_confidence() -> None:
    result = calibrate(
        {
            "technical_analyzer": technical(Bias.BULLISH),
            "fundamental_analyzer": fundamental(Bias.BULLISH),
            "news_analyzer": news(0.6),
        },
        supporting_count=4,
        conflicting_count=3,
    )
    assert result.confidence > 85


def test_confidence_never_reaches_certainty() -> None:
    """No analysis is certain, so the scale does not offer 100."""
    result = calibrate(
        {
            "technical_analyzer": technical(Bias.BULLISH),
            "fundamental_analyzer": fundamental(Bias.BULLISH),
            "news_analyzer": news(0.9),
        },
        supporting_count=5,
        conflicting_count=5,
    )
    assert result.confidence <= MAX_CONFIDENCE


def test_disagreement_lowers_confidence_against_an_otherwise_identical_case() -> None:
    agreeing = calibrate(
        {
            "technical_analyzer": technical(Bias.BULLISH),
            "fundamental_analyzer": fundamental(Bias.BULLISH),
        },
        supporting_count=3,
        conflicting_count=2,
    )
    conflicted = calibrate(
        {
            "technical_analyzer": technical(Bias.BULLISH),
            "fundamental_analyzer": fundamental(Bias.BEARISH),
        },
        supporting_count=3,
        conflicting_count=2,
    )
    assert conflicted.confidence < agreeing.confidence


def test_the_score_is_always_in_range() -> None:
    for supporting, conflicting in ((0, 0), (10, 0), (0, 10), (5, 5)):
        result = calibrate(
            {"technical_analyzer": technical(Bias.NEUTRAL)},
            supporting_count=supporting,
            conflicting_count=conflicting,
        )
        assert 0 <= result.confidence <= 100


def test_the_score_carries_an_explanation() -> None:
    """A number a user cannot interrogate is a number they cannot weigh."""
    result = calibrate(
        {"technical_analyzer": technical(Bias.BULLISH)}, supporting_count=2, conflicting_count=2
    )
    assert "coverage" in result.explanation
    assert "agreement" in result.explanation
    assert result.as_dict()["components"]["coverage"] > 0


# --- Signal extraction -----------------------------------------------------


def test_the_summary_agent_is_not_counted_as_an_evidence_source() -> None:
    """It summarises the others; counting it would double-count them."""
    from aidss.prompts.schemas import SynthesisOutput

    signals = signals_from_agent_outputs(
        {
            "technical_analyzer": technical(Bias.BULLISH),
            "summary_agent": SynthesisOutput(
                summary="s", confidence=50.0, overall_bias=Bias.BULLISH
            ),
        }
    )
    assert [s.agent for s in signals] == ["technical_analyzer"]


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.6, 1), (0.1, 0), (-0.1, 0), (-0.6, -1)],
)
def test_mild_sentiment_is_treated_as_noise(score: float, expected: int) -> None:
    signals = signals_from_agent_outputs({"news_analyzer": news(score)})
    assert signals[0].direction == expected


def test_evidence_direction_requires_unanimity() -> None:
    agreeing = [signal("technical_analyzer", 1), signal("news_analyzer", 1)]
    split = [signal("technical_analyzer", 1), signal("news_analyzer", -1)]
    assert evidence_direction(agreeing) == 1
    assert evidence_direction(split) is None


def test_evidence_direction_ignores_sources_without_data() -> None:
    direction = evidence_direction(
        [
            signal("technical_analyzer", -1),
            signal("news_analyzer", 1, DataSufficiency.INSUFFICIENT),
        ]
    )
    assert direction == -1


# --- Derived price levels --------------------------------------------------


SNAPSHOT = {
    "last_close": 9500.0,
    "levels": {"support": [9300.0, 9100.0], "resistance": [9700.0, 9900.0]},
    "indicators": {"atr(period=14)": {"value": 100.0}},
}


def test_levels_come_from_the_indicator_engine() -> None:
    levels = derive_levels(SNAPSHOT, RecommendationLabel.BUY)
    assert levels.support == Decimal("9300.00")
    assert levels.resistance == Decimal("9700.00")


def test_a_constructive_label_targets_the_nearest_resistance() -> None:
    levels = derive_levels(SNAPSHOT, RecommendationLabel.BUY)
    assert levels.target_price == Decimal("9700.00")
    assert "resistance" in levels.target_price_method


def test_a_cautious_label_targets_the_nearest_support() -> None:
    levels = derive_levels(SNAPSHOT, RecommendationLabel.SELL)
    assert levels.target_price == Decimal("9300.00")
    assert "support" in levels.target_price_method


def test_a_neutral_label_gets_no_target() -> None:
    """Section 5.4 asks for a target only where a basis exists."""
    levels = derive_levels(SNAPSHOT, RecommendationLabel.HOLD)
    assert levels.target_price is None
    assert levels.suggested_stop is None


def test_the_stop_is_two_atr_from_price_and_on_the_right_side() -> None:
    constructive = derive_levels(SNAPSHOT, RecommendationLabel.BUY)
    cautious = derive_levels(SNAPSHOT, RecommendationLabel.SELL)
    assert constructive.suggested_stop == Decimal("9300.00")  # 9500 - 2*100
    assert cautious.suggested_stop == Decimal("9700.00")  # 9500 + 2*100


def test_the_stop_is_labelled_a_suggestion_not_an_order() -> None:
    """Section 5.4 requires the wording as well as the field name."""
    method = derive_levels(SNAPSHOT, RecommendationLabel.BUY).suggested_stop_method
    assert "suggestion" in method.lower()
    assert "not an order" in method.lower()


def test_no_atr_means_no_stop_rather_than_a_guessed_one() -> None:
    snapshot = {**SNAPSHOT, "indicators": {}}
    assert derive_levels(snapshot, RecommendationLabel.BUY).suggested_stop is None


def test_no_levels_means_no_target() -> None:
    snapshot = {"last_close": 9500.0, "levels": {}, "indicators": {}}
    levels = derive_levels(snapshot, RecommendationLabel.BUY)
    assert levels.target_price is None
    assert levels.support is None


def test_an_empty_snapshot_is_handled() -> None:
    levels = derive_levels({}, RecommendationLabel.BUY)
    assert levels.support is None and levels.suggested_stop is None


def test_a_stop_is_never_negative() -> None:
    """A wide ATR on a low-priced stock must not produce a nonsensical level."""
    snapshot = {
        "last_close": 50.0,
        "levels": {"support": [40.0], "resistance": [60.0]},
        "indicators": {"atr(period=14)": {"value": 40.0}},
    }
    assert derive_levels(snapshot, RecommendationLabel.BUY).suggested_stop is None
