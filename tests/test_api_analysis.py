"""Analysis endpoint tests (Phase 4, Section 10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fixture_ai_provider(monkeypatch):
    """Route the API's AI layer at the deterministic provider.

    The endpoint builds its gateway from configuration, so pointing settings at
    the fixture adapter exercises the real provisioning path rather than
    patching the gateway out of the picture.
    """
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ingested(client: TestClient, auth_headers) -> None:
    response = client.post(
        "/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers
    )
    assert response.status_code == 200


def test_running_an_analysis_returns_agent_output(client, auth_headers, ingested) -> None:
    response = client.post("/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["ticker"] == "BBCA"
    assert "technical_analyzer" in body["agents"]
    assert "summary_agent" in body["agents"]
    assert body["analysis_result_id"]


def test_each_agent_output_carries_its_provenance(client, auth_headers, ingested) -> None:
    """Which model, from which prompt version - the traceability requirement."""
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    technical = body["agents"]["technical_analyzer"]
    assert technical["prompt_version"]
    assert technical["model"]
    assert technical["provider"]


def test_skipped_agents_are_reported_with_reasons(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    skipped = {s["agent"] for s in body["skipped"]}
    assert {"fundamental_analyzer", "news_analyzer"} <= skipped
    assert all(s["reason"] for s in body["skipped"])


def test_analysis_carries_a_disclaimer(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    disclaimer = body["disclaimer"].lower()
    assert "not investment advice" in disclaimer
    assert "no ability to place an order" in disclaimer


def test_no_agent_output_reports_conflict_rather_than_an_empty_success(
    client, auth_headers
) -> None:
    """An empty 200 would read as an analysis that found nothing to say."""
    client.post("/assets", json={"ticker": "NODATA"}, headers=auth_headers)
    response = client.post(
        "/assets/NODATA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    )
    assert response.status_code == 409
    assert response.json()["detail"]["skipped"]


def test_reading_a_stored_analysis_does_not_run_the_agents(
    client, auth_headers, ingested
) -> None:
    """GET must never trigger model calls - a run costs real money.

    Verified through the side effect a run cannot avoid: every run persists an
    ``analysis_results`` row, so an unchanged history proves nothing ran.
    """
    client.post("/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers)
    before = client.get("/assets/BBCA/analysis/history", headers=auth_headers).json()

    stored = client.get("/assets/BBCA/analysis", headers=auth_headers)
    assert stored.status_code == 200
    body = stored.json()
    assert "technical_analyzer" in body["agents"]
    assert body["usage"]["total_tokens"] > 0

    after = client.get("/assets/BBCA/analysis/history", headers=auth_headers).json()
    assert after == before


def test_reading_before_any_run_returns_404(client, auth_headers, ingested) -> None:
    response = client.get("/assets/BBCA/analysis", headers=auth_headers)
    assert response.status_code == 404
    assert "POST" in response.json()["detail"]


def test_history_lists_previous_runs(client, auth_headers, ingested) -> None:
    for _ in range(2):
        client.post("/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers)
    history = client.get("/assets/BBCA/analysis/history", headers=auth_headers)
    assert history.status_code == 200
    assert len(history.json()) == 2


def test_analysis_requires_authentication(client: TestClient) -> None:
    assert client.post("/assets/BBCA/analysis", json={}).status_code == 401


# --- Recommendation (Phase 5, Section 5.4) ---------------------------------

#: Every field Section 5.4 lists as mandatory.
SECTION_5_4_FIELDS = (
    "label",
    "confidence",
    "reasoning",
    "supporting_factors",
    "conflicting_factors",
    "risk_factors",
    "bullish_scenario",
    "bearish_scenario",
    "support_level",
    "resistance_level",
    "target_price",
    "suggested_stop",
    "horizon",
)


def test_analysis_includes_a_complete_recommendation(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()

    recommendation = body["recommendation"]
    assert recommendation is not None
    for field in SECTION_5_4_FIELDS:
        assert field in recommendation, f"Section 5.4 field missing: {field}"


def test_conflicting_factors_are_never_empty(client, auth_headers, ingested) -> None:
    """The structural defence against confirmation bias, checked at the edge."""
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    assert body["recommendation"]["conflicting_factors"]


def test_the_published_confidence_is_calibrated_not_self_reported(
    client, auth_headers, ingested
) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    recommendation = body["recommendation"]

    assert recommendation["model_self_reported_confidence"] == 75.0
    assert recommendation["confidence"] != 75.0
    # And it can be interrogated rather than merely trusted.
    assert "coverage" in recommendation["confidence_basis"]["components"]
    assert recommendation["confidence_basis"]["explanation"]


def test_price_fields_state_the_method_behind_them(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    recommendation = body["recommendation"]

    if recommendation["target_price"] is not None:
        assert recommendation["target_price_method"]
    if recommendation["suggested_stop"] is not None:
        # Section 5.4 requires the wording, not only the field name.
        assert "suggestion" in recommendation["suggested_stop_method"].lower()


def test_the_recommendation_can_be_read_back_on_its_own(client, auth_headers, ingested) -> None:
    client.post("/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers)

    response = client.get("/assets/BBCA/recommendation", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    for field in SECTION_5_4_FIELDS:
        assert field in body


def test_reading_a_recommendation_before_any_run_returns_404(
    client, auth_headers, ingested
) -> None:
    response = client.get("/assets/BBCA/recommendation", headers=auth_headers)
    assert response.status_code == 404
    assert "analysis" in response.json()["detail"]


def test_the_recommendation_step_can_be_skipped(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis",
        json={"timeframe": "1d", "include_recommendation": False},
        headers=auth_headers,
    ).json()
    assert body["recommendation"] is None
    assert body["agents"]


def test_the_label_is_one_of_the_six_graded_stances(client, auth_headers, ingested) -> None:
    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()
    assert body["recommendation"]["label"] in {
        "strong_buy",
        "buy",
        "watchlist",
        "hold",
        "reduce",
        "sell",
    }


def test_unknown_asset_returns_404(client, auth_headers) -> None:
    response = client.post("/assets/NOSUCH/analysis", json={}, headers=auth_headers)
    assert response.status_code == 404
