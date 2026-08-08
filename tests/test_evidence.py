"""The chart payload behind a recommendation.

One rule carries most of the weight: nothing on this chart may extend past the
last completed bar. A line sloping into the empty space to the right is a
forecast whatever the legend calls it, and this is the one place in the product
where drawing one would be easy and would look like a feature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aidss.db.models import (
    AnalysisResult,
    Asset,
    HistoricalPrice,
    Recommendation,
    RecommendationLabel,
)
from aidss.domain.types import Timeframe
from aidss.recommendations.evidence import EVIDENCE_CAVEAT, for_recommendation


def seed_asset(session, ticker="BBRI", bars=90) -> Asset:
    asset = Asset(ticker=ticker, exchange="IDX", name=ticker)
    session.add(asset)
    session.flush()

    start = datetime(2026, 1, 5, tzinfo=UTC)
    for index in range(bars):
        price = Decimal(str(100 + index * 0.5))
        session.add(
            HistoricalPrice(
                asset_id=asset.id,
                timeframe=Timeframe.D1,
                timestamp=start + timedelta(days=index),
                open=price,
                high=price * Decimal("1.01"),
                low=price * Decimal("0.99"),
                close=price,
                volume=Decimal("1000000"),
                source="test",
            )
        )
    session.flush()
    return asset


def seed_recommendation(session, asset: Asset) -> Recommendation:
    result = AnalysisResult(
        asset_id=asset.id, analysis_type="multi_agent", context_snapshot={}
    )
    session.add(result)
    session.flush()
    row = Recommendation(
        analysis_result_id=result.id,
        label=RecommendationLabel.BUY,
        confidence=62,
        reasoning="Because of the stated conditions.",
        bullish_scenario="If it holds above support, the range top is the next level.",
        bearish_scenario="A close below support puts the prior low in play.",
        supporting_factors=["price is above its 50-bar average"],
        conflicting_factors=["volume has not confirmed the move"],
        support_level=Decimal("120"),
        resistance_level=Decimal("160"),
        target_price=Decimal("170"),
        suggested_stop=Decimal("115"),
        horizon="medium",
        language="en",
    )
    session.add(row)
    session.flush()
    return row


def test_no_recommendation_returns_nothing(session) -> None:
    """An empty state saying "run an analysis" beats a bare price chart under a
    heading that promises an explanation."""
    seed_asset(session)

    assert for_recommendation(session, "BBRI") is None


def test_an_unknown_ticker_returns_nothing(session) -> None:
    assert for_recommendation(session, "NOPE") is None


def test_every_named_level_is_marked(session) -> None:
    asset = seed_asset(session)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI")

    keys = {level.key for level in evidence.levels}
    assert keys == {"support_level", "resistance_level", "target_price", "suggested_stop"}


def test_every_level_states_its_basis(session) -> None:
    """A number with no stated basis is treated by the reader as more certain
    than it is - the rule the PDF export already follows."""
    asset = seed_asset(session)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI")

    assert all(level.basis for level in evidence.levels)


def test_the_stop_is_marked_as_suggested(session) -> None:
    asset = seed_asset(session)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI")
    stop = next(level for level in evidence.levels if level.key == "suggested_stop")

    assert "suggested" in stop.basis
    assert "not instructed" in stop.basis


def test_contradicting_factors_are_included(session) -> None:
    """A chart drawing only what agrees with the stance is an argument, not an
    explanation - the same reason Section 14.4 makes them a required field."""
    asset = seed_asset(session)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI")

    assert any(mark["side"] == "conflicting" for mark in evidence.marks)
    assert any(mark["side"] == "supporting" for mark in evidence.marks)


def test_no_bar_is_dated_after_the_last_one(session) -> None:
    """The rule that keeps this a chart rather than a projection."""
    asset = seed_asset(session, bars=60)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI")

    stamps = [bar["t"] for bar in evidence.bars]
    assert stamps == sorted(stamps)
    assert len(stamps) == 60


def test_the_caveat_denies_projection_explicitly(session) -> None:
    assert "is projected forward" in EVIDENCE_CAVEAT
    assert "not as a path" in EVIDENCE_CAVEAT
    assert "beyond the last completed bar" in EVIDENCE_CAVEAT


def test_a_level_outside_the_price_range_is_still_returned(session) -> None:
    """Clipping a target above every bar would draw it at the top edge, which
    reads as "just reached" - the opposite of what it means."""
    asset = seed_asset(session, bars=60)
    session.add(
        Recommendation(
            analysis_result_id=seed_recommendation(session, asset).analysis_result_id,
            label=RecommendationLabel.BUY,
            confidence=60,
            reasoning="x",
            bullish_scenario="x",
            bearish_scenario="x",
            target_price=Decimal("9999"),
            horizon="medium",
            language="en",
        )
    )
    session.flush()

    evidence = for_recommendation(session, "BBRI")
    target = next(
        (level for level in evidence.levels if level.key == "target_price"), None
    )

    assert target is not None


def test_decimals_survive_as_strings(session) -> None:
    """Sent as JSON numbers, a rupiah price loses precision silently."""
    asset = seed_asset(session, bars=60)
    seed_recommendation(session, asset)

    evidence = for_recommendation(session, "BBRI").as_dict()

    assert isinstance(evidence["bars"][0]["c"], str)
    assert isinstance(evidence["levels"][0]["price"], str)


# --- the endpoint -----------------------------------------------------------


def test_the_endpoint_explains_an_absent_recommendation(client, auth_headers) -> None:
    response = client.get("/assets/NOPE/evidence", headers=auth_headers)

    assert response.status_code == 404
    assert "Run an analysis" in response.json()["detail"]


def test_the_endpoint_needs_authentication(client) -> None:
    assert client.get("/assets/BBRI/evidence").status_code == 401
