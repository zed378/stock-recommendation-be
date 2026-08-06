"""Journal, reflection, conversation, audit log, and fundamentals.

Completes Section 10's endpoint surface and Section 5.2's agent roster.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aidss.agents.conversation import ChatMode, ReflectionAgent, ReflectionContext
from aidss.agents.memory import InvestorMemory


@pytest.fixture(autouse=True)
def fixture_providers(monkeypatch):
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    monkeypatch.setenv("AIDSS_NEWS_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def add_entries(client: TestClient, headers, count: int) -> None:
    for i in range(count):
        client.post(
            "/journal",
            json={
                "decision": "held" if i % 2 else "added",
                "note": f"Entry {i}: my reasoning at the time.",
                "ticker": "BBCA",
            },
            headers=headers,
        )


# --- Journal ---------------------------------------------------------------


def test_an_entry_records_what_the_investor_decided(client, auth_headers) -> None:
    response = client.post(
        "/journal",
        json={"decision": "waited", "note": "Not confident either way.", "ticker": "BBCA"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "waited"
    assert body["ticker"] == "BBCA"


def test_the_decision_field_is_free_text(client, auth_headers) -> None:
    """A closed vocabulary would push people toward the platform's words."""
    response = client.post(
        "/journal",
        json={"decision": "sat on my hands and regretted it later"},
        headers=auth_headers,
    )
    assert response.status_code == 201


def test_an_entry_needs_no_ticker(client, auth_headers) -> None:
    """Not every decision is about one holding."""
    response = client.post(
        "/journal",
        json={"decision": "raised cash", "note": "Uncomfortable with overall exposure."},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["ticker"] is None


def test_a_reference_to_a_missing_recommendation_is_rejected(client, auth_headers) -> None:
    import uuid

    response = client.post(
        "/journal",
        json={"decision": "added", "recommendation_ref": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_entries_are_scoped_to_their_owner(client, auth_headers) -> None:
    created = client.post("/journal", json={"decision": "added"}, headers=auth_headers).json()

    client.post(
        "/auth/register",
        json={"email": "other-journal@example.com", "password": "correct-horse-battery"},
    )
    token = client.post(
        "/auth/login",
        json={"email": "other-journal@example.com", "password": "correct-horse-battery"},
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.get("/journal", headers=other).json() == []
    assert client.delete(f"/journal/{created['id']}", headers=other).status_code == 404


def test_the_summary_needs_no_model_call(client, auth_headers) -> None:
    add_entries(client, auth_headers, 4)
    body = client.get("/journal/summary", headers=auth_headers).json()
    assert body["entries"] == 4
    assert set(body["by_decision"]) == {"added", "held"}
    assert body["first_entry_at"]


# --- Reflection ------------------------------------------------------------


def test_reflection_needs_enough_entries_to_find_a_pattern(client, auth_headers) -> None:
    """Below the floor there is no pattern to find, only noise to narrate."""
    add_entries(client, auth_headers, 2)
    response = client.post("/journal/reflection", headers=auth_headers)
    assert response.status_code == 409
    assert "at least" in response.json()["detail"]


def test_reflection_reports_patterns_and_its_own_blind_spots(client, auth_headers) -> None:
    add_entries(client, auth_headers, 5)
    body = client.post("/journal/reflection", headers=auth_headers).json()

    assert body["entries_reviewed"] == 5
    assert body["patterns"]
    # Naming what the journal cannot support is what stops the agent inventing it.
    assert body["insufficient_evidence_for"]
    assert body["questions_to_consider"]


def test_the_reflection_disclaimer_says_what_it_is_not(client, auth_headers) -> None:
    add_entries(client, auth_headers, 5)
    disclaimer = client.post("/journal/reflection", headers=auth_headers).json()["disclaimer"]
    lowered = disclaimer.lower()
    assert "not an assessment of your returns" in lowered
    assert "not investment advice" in lowered


def test_the_reflection_states_which_language_it_is_in(client, auth_headers) -> None:
    """The output language is a server setting, so a reader with the interface
    in English is still looking at Indonesian prose on a default deployment. A
    switch that inferred the language from the locale offered to translate the
    text into the language it was already written in - and then had to fetch,
    every time, a translation that could never match."""
    from aidss.config import get_settings

    add_entries(client, auth_headers, 5)
    body = client.post("/journal/reflection", headers=auth_headers).json()
    assert body["language"] == get_settings().analysis_language


def test_the_reflection_agent_routes_as_sensitive() -> None:
    """A decision journal is a record of someone's thinking about their money."""
    from aidss.llm.router import Sensitivity

    assert ReflectionAgent.sensitivity is Sensitivity.SENSITIVE


def test_the_entry_floor_is_enforced_on_the_agent_itself() -> None:
    agent = ReflectionAgent()
    memory = InvestorMemory(user_id=None, preferences={})
    assert not agent.is_applicable(ReflectionContext(memory=memory, entries=[{"x": 1}]))
    assert agent.is_applicable(
        ReflectionContext(memory=memory, entries=[{"x": i} for i in range(3)])
    )


# --- Chat ------------------------------------------------------------------


def test_learn_mode_explains_a_concept(client, auth_headers) -> None:
    body = client.post(
        "/chat",
        json={"question": "What does RSI measure?", "mode": "learn"},
        headers=auth_headers,
    ).json()
    assert body["agent"] == "learning_assistant"
    assert body["answer"]
    assert body["disclaimer"]


def test_knowledge_mode_answers_from_the_knowledge_base(
    client, auth_headers, admin_headers
) -> None:
    client.post(
        "/knowledge-base",
        json={
            "title": "RSI",
            "content": "The relative strength index measures the speed of price changes.",
        },
        headers=admin_headers,
    )
    body = client.post(
        "/chat",
        json={"question": "What does RSI measure?", "mode": "knowledge"},
        headers=auth_headers,
    ).json()

    assert body["agent"] == "knowledge_agent"
    # The passages are returned, so the answer can be checked against them.
    assert body["retrieved"]
    assert "score" in body["retrieved"][0]


def test_research_mode_requires_a_ticker(client, auth_headers) -> None:
    """The mode is chosen by the caller, so a missing input is a clear 422."""
    response = client.post(
        "/chat",
        json={"question": "How is the business doing?", "mode": "research"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "ticker" in response.json()["detail"]


def test_research_mode_is_grounded_in_ingested_data(client, auth_headers) -> None:
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    body = client.post(
        "/chat",
        json={"question": "What has price been doing?", "mode": "research", "ticker": "BBCA"},
        headers=auth_headers,
    ).json()
    assert body["agent"] == "research_agent"
    assert body["answer"]


def test_the_mode_is_supplied_not_inferred() -> None:
    """Guessing intent would add a classifier that can be wrong."""
    assert set(ChatMode) == {ChatMode.LEARN, ChatMode.RESEARCH, ChatMode.KNOWLEDGE}


def test_an_empty_sources_list_is_visible_to_the_caller(client, auth_headers) -> None:
    """It means the model answered from training, and the reader should know."""
    body = client.post(
        "/chat",
        json={"question": "What is a moving average?", "mode": "learn"},
        headers=auth_headers,
    ).json()
    assert "sources_used" in body


def test_chat_requires_authentication(client: TestClient) -> None:
    assert client.post("/chat", json={"question": "anything"}).status_code == 401


# --- Audit log -------------------------------------------------------------


def test_the_audit_log_is_admin_only(client, auth_headers) -> None:
    assert client.get("/audit-logs", headers=auth_headers).status_code == 403


def test_registration_is_recorded(client, admin_headers) -> None:
    client.post(
        "/auth/register",
        json={"email": "audited@example.com", "password": "correct-horse-battery"},
    )
    body = client.get("/audit-logs?entity=users", headers=admin_headers).json()["items"]
    assert any(row["action"] == "register" for row in body)


def test_the_audit_log_can_be_filtered_by_actor(client, admin_headers) -> None:
    client.post(
        "/auth/register",
        json={"email": "audited2@example.com", "password": "correct-horse-battery"},
    )
    body = client.get("/audit-logs?actor_type=user", headers=admin_headers).json()["items"]
    assert all(row["actor_type"] == "user" for row in body)


def test_an_analysis_can_be_reproduced_from_the_audit_trail(
    client, auth_headers, admin_headers
) -> None:
    """Section 1's full-traceability requirement, exercised end to end."""
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    analysis = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()

    body = client.get(
        f"/audit-logs/analysis/{analysis['analysis_result_id']}", headers=admin_headers
    ).json()

    assert body["ticker"] == "BBCA"
    assert body["prompt_version"]
    assert body["model_used"]
    # Both halves: what the agents saw, and what they said.
    assert body["context_and_output"]["context"]["indicators"]
    assert body["context_and_output"]["result"]["agents"]


def test_there_is_no_endpoint_that_writes_an_audit_log() -> None:
    """An audit log the application can edit is not an audit log."""
    from aidss.main import create_app

    paths = create_app().openapi()["paths"]
    for path, operations in paths.items():
        if "audit-log" in path:
            assert set(operations) <= {"get"}, f"{path} exposes a write method"


# --- Fundamentals ----------------------------------------------------------


def test_a_provider_without_fundamentals_says_so_rather_than_failing(
    client, auth_headers
) -> None:
    """The fixture market provider publishes none - a fact, not an error."""
    response = client.post("/assets/BBCA/fundamentals/ingest", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["unsupported"] is True
    assert body["fetched"] == 0
    assert "no fundamental data" in body["note"]


def test_fundamentals_can_be_listed(client, auth_headers, session) -> None:
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from aidss.db.models import Asset, FundamentalMetric

    client.post("/assets", json={"ticker": "FUND"}, headers=auth_headers)
    asset = session.scalar(select(Asset).where(Asset.ticker == "FUND"))
    session.add(
        FundamentalMetric(
            asset_id=asset.id,
            period=date(2025, 6, 30),
            period_type="ttm",
            metric_name="pe_ratio",
            value=Decimal("18.4"),
            source="test",
        )
    )
    session.commit()

    body = client.get("/assets/FUND/fundamentals", headers=auth_headers).json()
    assert len(body) == 1
    assert body[0]["metric"] == "pe_ratio"
    # The basis travels with the number: a quarterly figure read as annual is a
    # factor-of-four error.
    assert body[0]["period_type"] == "ttm"


def test_stored_fundamentals_stop_the_analyzer_skipping(
    client, auth_headers, session
) -> None:
    """The end of the chain: coverage rises, and so does calibrated confidence."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from aidss.db.models import Asset, FundamentalMetric

    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    asset = session.scalar(select(Asset).where(Asset.ticker == "BBCA"))
    for metric, value in (("pe_ratio", "18.4"), ("return_on_equity", "0.19")):
        session.add(
            FundamentalMetric(
                asset_id=asset.id,
                period=date(2025, 6, 30),
                period_type="ttm",
                metric_name=metric,
                value=Decimal(value),
                source="test",
            )
        )
    session.commit()

    body = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()

    assert "fundamental_analyzer" in body["agents"]
    assert "fundamental_analyzer" not in {s["agent"] for s in body["skipped"]}
