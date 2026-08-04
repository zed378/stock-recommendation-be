"""Portfolio analysis and simulation endpoints (Phase 6, Section 10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fixture_ai_provider(monkeypatch):
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def funded(client: TestClient, auth_headers) -> None:
    """A two-holding portfolio with real stored price history behind it."""
    for ticker in ("BBCA", "TLKM"):
        client.post(
            f"/assets/{ticker}/ingest",
            json={"timeframe": "1d", "days": 400},
            headers=auth_headers,
        )
    client.post(
        "/portfolio/holdings",
        json={"ticker": "BBCA", "quantity": "100", "average_price": "9000"},
        headers=auth_headers,
    )
    client.post(
        "/portfolio/holdings",
        json={"ticker": "TLKM", "quantity": "500", "average_price": "3000"},
        headers=auth_headers,
    )


# --- Analysis --------------------------------------------------------------


def test_analysis_reports_deterministic_metrics(client, auth_headers, funded) -> None:
    body = client.post("/portfolio/analysis", headers=auth_headers).json()

    metrics = body["metrics"]
    assert metrics["position_count"] == 2
    assert sum(metrics["weights"].values()) == pytest.approx(1.0)
    assert metrics["concentration_hhi"] > 0
    assert metrics["concentration_reading"]


def test_analysis_includes_both_agent_narratives(client, auth_headers, funded) -> None:
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    assert "portfolio_analyzer" in body["agents"]
    assert "risk_analyzer" in body["agents"]
    assert body["failed"] == []


def test_risk_figures_state_that_they_are_historical(client, auth_headers, funded) -> None:
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    assert "not a forecast" in body["risk"]["basis"]
    assert body["risk"]["observations"] > 0


def test_the_risk_agent_names_its_own_limitations(client, auth_headers, funded) -> None:
    """A risk report that does not say what it cannot see invites misreading."""
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    assert body["agents"]["risk_analyzer"]["limitations"]


def test_analysis_carries_a_disclaimer(client, auth_headers, funded) -> None:
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    disclaimer = body["disclaimer"].lower()
    assert "you entered yourself" in disclaimer
    assert "cannot place an order" in disclaimer
    assert "historical" in disclaimer


def test_an_empty_portfolio_skips_both_agents_with_reasons(client, auth_headers) -> None:
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    skipped = {s["agent"]: s["reason"] for s in body["skipped"]}
    assert {"portfolio_analyzer", "risk_analyzer"} <= set(skipped)
    assert all(reason for reason in skipped.values())
    assert body["agents"] == {}


def test_a_holding_without_price_history_is_flagged_not_hidden(
    client, auth_headers
) -> None:
    """Valuing at cost is a real fallback; it must be visible."""
    client.post(
        "/portfolio/holdings",
        json={"ticker": "NOPRICE", "quantity": "10", "average_price": "1000"},
        headers=auth_headers,
    )
    body = client.post("/portfolio/analysis", headers=auth_headers).json()
    assert body["metrics"]["priced_positions"] == 0
    assert body["holdings"][0]["valued_at_cost"] is True


def test_reading_the_analysis_does_not_call_a_model(client, auth_headers, funded) -> None:
    """GET recomputes the cheap arithmetic; only POST buys a narrative.

    The route is wired with a provider-less gateway, so an accidental agent
    call would raise rather than quietly spend money.
    """
    response = client.get("/portfolio/analysis", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["metrics"]["position_count"] == 2


def test_portfolio_analysis_requires_authentication(client: TestClient) -> None:
    assert client.post("/portfolio/analysis").status_code == 401


# --- Simulation ------------------------------------------------------------


def test_simulation_reports_before_after_and_the_delta(client, auth_headers, funded) -> None:
    body = client.post(
        "/portfolio/simulate",
        json={"changes": [{"ticker": "BBCA", "quantity": "500"}]},
        headers=auth_headers,
    ).json()

    assert body["before"]["portfolio"]["position_count"] == 2
    assert body["after"]["portfolio"]["position_count"] == 2
    assert body["deltas"]["concentration_hhi"] > 0
    assert body["changes"][0]["action"] == "resize"


def test_simulation_leaves_the_stored_portfolio_untouched(
    client, auth_headers, funded
) -> None:
    """The distinction the whole product rests on: a question, not a decision."""
    before = client.get("/portfolio", headers=auth_headers).json()

    client.post(
        "/portfolio/simulate",
        json={
            "changes": [
                {"ticker": "BBCA", "quantity": "9999"},
                {"ticker": "TLKM", "quantity": "0"},
            ]
        },
        headers=auth_headers,
    )

    after = client.get("/portfolio", headers=auth_headers).json()
    assert after == before


def test_removing_a_holding_in_simulation_lowers_diversification(
    client, auth_headers, funded
) -> None:
    body = client.post(
        "/portfolio/simulate",
        json={"changes": [{"ticker": "TLKM", "quantity": "0"}]},
        headers=auth_headers,
    ).json()
    assert body["deltas"]["position_count"] == -1
    assert body["deltas"]["diversification_score"] < 0


def test_simulating_an_unheld_asset_is_a_422(client, auth_headers, funded) -> None:
    response = client.post(
        "/portfolio/simulate",
        json={"changes": [{"ticker": "GOTO", "quantity": "100"}]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "reference price" in response.json()["detail"]


def test_emptying_the_portfolio_in_simulation_is_a_422(client, auth_headers, funded) -> None:
    response = client.post(
        "/portfolio/simulate",
        json={
            "changes": [
                {"ticker": "BBCA", "quantity": "0"},
                {"ticker": "TLKM", "quantity": "0"},
            ]
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_a_negative_quantity_is_rejected_by_the_schema(client, auth_headers, funded) -> None:
    response = client.post(
        "/portfolio/simulate",
        json={"changes": [{"ticker": "BBCA", "quantity": "-1"}]},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_simulation_states_that_nothing_was_changed(client, auth_headers, funded) -> None:
    body = client.post(
        "/portfolio/simulate",
        json={"changes": [{"ticker": "BBCA", "quantity": "50"}]},
        headers=auth_headers,
    ).json()
    assert "Nothing was changed" in body["note"]
