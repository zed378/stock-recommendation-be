"""Knowledge base and news-schedule endpoints (Phase 7, Sections 6.3, 10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fixture_providers(monkeypatch):
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    monkeypatch.setenv("AIDSS_NEWS_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def registered_asset(client: TestClient, auth_headers) -> None:
    client.post("/assets", json={"ticker": "BBCA"}, headers=auth_headers)


# --- Knowledge base --------------------------------------------------------


def test_a_document_is_stored_and_chunked(client, admin_headers) -> None:
    response = client.post(
        "/knowledge-base",
        json={
            "title": "Reading the RSI",
            "category": "education",
            "content": "The relative strength index measures the speed of price changes. "
            "Readings above seventy are conventionally called overbought, though the "
            "label describes momentum rather than valuation.",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chunks"] >= 1
    assert body["title"] == "Reading the RSI"


def test_writing_to_the_knowledge_base_is_admin_only(client, auth_headers) -> None:
    """It shapes what every agent retrieves, so it is system configuration."""
    response = client.post(
        "/knowledge-base",
        json={"title": "x", "content": "some content"},
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_documents_can_be_listed_with_their_chunk_counts(client, admin_headers) -> None:
    client.post(
        "/knowledge-base",
        json={"title": "Doc A", "content": "Content about dividend yield and payout ratios."},
        headers=admin_headers,
    )
    body = client.get("/knowledge-base", headers=admin_headers).json()
    assert len(body) == 1
    assert body[0]["chunks"] >= 1


def test_knowledge_search_returns_scored_results(client, admin_headers) -> None:
    client.post(
        "/knowledge-base",
        json={"title": "Doc", "content": "Dividend yield measures income relative to price."},
        headers=admin_headers,
    )
    body = client.get("/knowledge-base/search?q=dividend+yield", headers=admin_headers).json()
    assert body["query"] == "dividend yield"
    assert body["results"]
    assert "score" in body["results"][0]


def test_searching_an_empty_knowledge_base_returns_no_results(client, auth_headers) -> None:
    body = client.get("/knowledge-base/search?q=anything", headers=auth_headers).json()
    assert body["results"] == []


# --- Cron presets ----------------------------------------------------------


def test_presets_are_offered_so_nobody_writes_cron_by_hand(client, auth_headers) -> None:
    body = client.get("/news-schedules/presets", headers=auth_headers).json()
    assert len(body) >= 5
    keys = {p["key"] for p in body}
    assert {"every_15_minutes", "hourly", "daily_premarket", "weekly"} <= keys
    assert all(p["suited_to"] for p in body)


# --- Schedules -------------------------------------------------------------


def test_a_schedule_is_created_from_a_preset(client, auth_headers, registered_asset) -> None:
    response = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["cron_expression"] == "0 7 * * 1-5"
    assert body["next_run_at"] is not None
    assert body["status"] == "active"


def test_a_custom_expression_is_accepted(client, auth_headers, registered_asset) -> None:
    response = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "cron_expression": "30 9 * * 1-5"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["preset_label"] is None


def test_a_too_frequent_schedule_is_refused(client, auth_headers, registered_asset) -> None:
    """The Section 6.3.4 guardrail, applied where the user chooses the cadence."""
    response = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "cron_expression": "* * * * *"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "minimum" in response.json()["detail"].lower()


def test_a_malformed_expression_is_refused(client, auth_headers, registered_asset) -> None:
    response = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "cron_expression": "every monday please"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_a_schedule_for_an_unknown_asset_is_a_404(client, auth_headers) -> None:
    response = client.post(
        "/news-schedules",
        json={"ticker": "NOSUCH", "preset": "weekly"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_the_same_schedule_cannot_be_created_twice(client, auth_headers, registered_asset) -> None:
    payload = {"ticker": "BBCA", "preset": "weekly"}
    client.post("/news-schedules", json=payload, headers=auth_headers)
    assert client.post("/news-schedules", json=payload, headers=auth_headers).status_code == 409


def test_different_cadences_for_one_asset_are_allowed(
    client, auth_headers, registered_asset
) -> None:
    client.post(
        "/news-schedules", json={"ticker": "BBCA", "preset": "weekly"}, headers=auth_headers
    )
    second = client.post(
        "/news-schedules", json={"ticker": "BBCA", "preset": "hourly"}, headers=auth_headers
    )
    assert second.status_code == 201


def test_schedules_are_scoped_to_their_owner(client, auth_headers, registered_asset) -> None:
    created = client.post(
        "/news-schedules", json={"ticker": "BBCA", "preset": "weekly"}, headers=auth_headers
    ).json()

    client.post(
        "/auth/register",
        json={"email": "other-news@example.com", "password": "correct-horse-battery"},
    )
    token = client.post(
        "/auth/login",
        json={"email": "other-news@example.com", "password": "correct-horse-battery"},
    ).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}

    assert client.get("/news-schedules", headers=other).json() == []
    assert client.delete(f"/news-schedules/{created['id']}", headers=other).status_code == 404


def test_a_schedule_can_be_deleted(client, auth_headers, registered_asset) -> None:
    created = client.post(
        "/news-schedules", json={"ticker": "BBCA", "preset": "weekly"}, headers=auth_headers
    ).json()
    deleted = client.delete(f"/news-schedules/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/news-schedules", headers=auth_headers).json() == []


# --- Manual run ------------------------------------------------------------


def test_running_a_schedule_now_ingests_and_indexes(
    client, auth_headers, registered_asset
) -> None:
    created = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    ).json()

    response = client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["fetched"] > 0
    assert body["inserted"] > 0
    assert body["chunks_indexed"] > 0
    assert body["next_run_at"] is not None
    assert body["error"] is None
    # Every ingested article is scored, with no index left dangling.
    assert body["scored"] == body["inserted"]
    assert body["warnings"] == []


def test_running_twice_stores_nothing_new(client, auth_headers, registered_asset) -> None:
    """The same idempotency the scheduler relies on, exercised through the API."""
    created = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    ).json()

    client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers)
    second = client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers).json()

    assert second["inserted"] == 0
    assert second["chunks_indexed"] == 0


def test_ingested_news_is_readable_with_its_sentiment(
    client, auth_headers, registered_asset
) -> None:
    created = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    ).json()
    client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers)

    body = client.get("/assets/BBCA/news", headers=auth_headers).json()
    assert body
    assert body[0]["headline"]
    assert body[0]["is_indexed"] is True


def test_ingested_news_becomes_searchable(client, auth_headers, registered_asset) -> None:
    created = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    ).json()
    client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers)

    body = client.get("/assets/BBCA/news/search?q=quarterly", headers=auth_headers).json()
    assert body["results"]
    assert body["results"][0]["source"] == "news"


def test_news_ingestion_feeds_the_news_analyzer(client, auth_headers, registered_asset) -> None:
    """The end of the Phase 7 chain: the analyzer stops skipping."""
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    created = client.post(
        "/news-schedules",
        json={"ticker": "BBCA", "preset": "daily_premarket"},
        headers=auth_headers,
    ).json()
    client.post(f"/news-schedules/{created['id']}/run-now", headers=auth_headers)

    analysis = client.post(
        "/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers
    ).json()

    assert "news_analyzer" in analysis["agents"]
    assert "news_analyzer" not in {s["agent"] for s in analysis["skipped"]}
