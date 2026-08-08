"""Reporting, notifications, and the operations overview (Phase 8, Section 7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aidss.db.models import Notification, User
from aidss.reporting.notifications import (
    SUBJECTS,
    DatabaseChannel,
    NotificationChannel,
    NotificationEvent,
    NotificationService,
)
from aidss.reporting.operations import build_overview
from aidss.security.passwords import hash_password


@pytest.fixture(autouse=True)
def fixture_providers(monkeypatch):
    monkeypatch.setenv("AIDSS_AI_PROVIDER", "fixture")
    monkeypatch.setenv("AIDSS_NEWS_PROVIDER", "fixture")
    from aidss.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def analysed(client: TestClient, auth_headers) -> None:
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    client.post("/assets/BBCA/analysis", json={"timeframe": "1d"}, headers=auth_headers)


@pytest.fixture
def funded(client: TestClient, auth_headers) -> None:
    client.post("/assets/BBCA/ingest", json={"timeframe": "1d", "days": 400}, headers=auth_headers)
    client.post(
        "/portfolio/holdings",
        json={"ticker": "BBCA", "quantity": "100", "average_price": "9000"},
        headers=auth_headers,
    )


# --- Asset report ----------------------------------------------------------


def test_the_report_contains_the_recommendation(client, auth_headers, analysed) -> None:
    body = client.get("/assets/BBCA/report", headers=auth_headers).json()
    assert body["title"].startswith("BBCA")
    assert "Recommendation" in body["markdown"]
    assert body["payload"]["recommendation"]


def test_counter_evidence_is_given_equal_prominence(client, auth_headers, analysed) -> None:
    """A report that buries what argues against it is an argument, not analysis."""
    markdown = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    assert "### Supporting" in markdown
    assert "### Arguing against" in markdown
    assert "### Risks" in markdown


def test_the_report_explains_how_the_confidence_was_reached(
    client, auth_headers, analysed
) -> None:
    markdown = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    assert "coverage" in markdown
    assert "agreement" in markdown


def test_what_was_not_covered_is_named(client, auth_headers, analysed) -> None:
    """Absent evidence is part of the finding, not an omission to hide."""
    markdown = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    assert "Not covered" in markdown
    assert "fundamental" in markdown.lower()


def test_the_report_carries_a_disclaimer(client, auth_headers, analysed) -> None:
    markdown = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    assert "not investment advice" in markdown.lower()
    assert "cannot place an order" in markdown.lower()


def test_markdown_can_be_served_as_the_response_body(client, auth_headers, analysed) -> None:
    response = client.get("/assets/BBCA/report?format=markdown", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# BBCA")


def test_a_report_without_a_stored_analysis_is_a_404(client, auth_headers) -> None:
    client.post("/assets", json={"ticker": "EMPTY"}, headers=auth_headers)
    response = client.get("/assets/EMPTY/report", headers=auth_headers)
    assert response.status_code == 404
    assert "Run one" in response.json()["detail"]


def test_generating_a_report_does_not_run_the_agents(client, auth_headers, analysed) -> None:
    """Opening a report must not cost money, or say something different each time."""
    before = client.get("/assets/BBCA/analysis/history", headers=auth_headers).json()
    first = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    second = client.get("/assets/BBCA/report", headers=auth_headers).json()["markdown"]
    after = client.get("/assets/BBCA/analysis/history", headers=auth_headers).json()

    assert after == before
    assert first == second


# --- Portfolio report ------------------------------------------------------


def test_the_portfolio_report_lists_holdings_and_risk(client, auth_headers, funded) -> None:
    body = client.get("/portfolio/report", headers=auth_headers).json()
    markdown = body["markdown"]
    assert "| Ticker |" in markdown
    assert "BBCA" in markdown
    assert "Historical risk" in markdown


def test_the_portfolio_report_states_that_risk_is_historical(
    client, auth_headers, funded
) -> None:
    markdown = client.get("/portfolio/report", headers=auth_headers).json()["markdown"]
    assert "not a forecast" in markdown


def test_an_empty_portfolio_report_is_a_404(client, auth_headers) -> None:
    response = client.get("/portfolio/report", headers=auth_headers)
    assert response.status_code == 404


def test_unavailable_risk_figures_are_explained_not_omitted(client, auth_headers) -> None:
    """A blank must read as "not enough data", never as "no risk"."""
    client.post(
        "/portfolio/holdings",
        json={"ticker": "NOPRICE", "quantity": "10", "average_price": "1000"},
        headers=auth_headers,
    )
    markdown = client.get("/portfolio/report", headers=auth_headers).json()["markdown"]
    assert "Figures not available" in markdown


# --- Notifications ---------------------------------------------------------


@pytest.fixture
def user(session) -> User:
    row = User(email="notify@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(row)
    session.flush()
    return row


def test_a_notification_is_stored_and_delivered(session, user) -> None:
    service = NotificationService(session)
    results = service.notify(user.id, NotificationEvent.ANALYSIS_READY, "BBCA analysis is ready.")

    assert results[0].delivered
    row = session.scalar(select(Notification))
    assert row.subject == SUBJECTS[NotificationEvent.ANALYSIS_READY]
    assert row.status == "delivered"


def test_the_row_is_written_before_delivery_is_attempted(session, user) -> None:
    """A notification must not be lost because a channel was down."""

    class BrokenChannel(NotificationChannel):
        name = "broken"

        def deliver(self, user, subject, message):
            return False

    service = NotificationService(session, channels=[BrokenChannel()])
    results = service.notify(user.id, NotificationEvent.INGESTION_FAILED, "Provider down.")

    assert not results[0].delivered
    row = session.scalar(select(Notification))
    assert row is not None, "the notification must survive a failed delivery"
    assert row.status == "failed"


def test_no_event_type_can_carry_an_instruction() -> None:
    """Section 7: alerts are about the system, never about what to do with money."""
    for event in NotificationEvent:
        subject = SUBJECTS[event].lower()
        for word in ("buy", "sell", "trade", "order"):
            assert word not in subject, f"{event.value} subject reads as an instruction"


def test_every_event_has_a_subject() -> None:
    assert set(SUBJECTS) == set(NotificationEvent)


def test_notifications_are_scoped_to_their_owner(session, user) -> None:
    other = User(email="other-notify@example.com", password_hash=hash_password("correct-horse-b"))
    session.add(other)
    session.flush()

    service = NotificationService(session)
    service.notify(user.id, NotificationEvent.REPORT_READY, "Your report is ready.")
    assert service.unread(other.id) == []


def test_marking_read_removes_it_from_the_unread_list(session, user) -> None:
    service = NotificationService(session)
    result = service.notify(user.id, NotificationEvent.NEWS_INGESTED, "New coverage.")[0]

    assert service.mark_read(user.id, result.notification_id) is True
    assert service.unread(user.id) == []


def test_marking_someone_elses_notification_read_fails(session, user) -> None:
    other = User(email="third@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(other)
    session.flush()

    service = NotificationService(session)
    result = service.notify(user.id, NotificationEvent.NEWS_INGESTED, "New coverage.")[0]
    assert service.mark_read(other.id, result.notification_id) is False


def test_an_unknown_channel_is_rejected(session, user) -> None:
    service = NotificationService(session, channels=[DatabaseChannel()])
    with pytest.raises(LookupError, match="channel"):
        service.notify(user.id, NotificationEvent.REPORT_READY, "x", channel="carrier-pigeon")


def test_notifications_are_readable_over_the_api(client, auth_headers, session) -> None:
    from aidss.db.models import User as UserModel

    investor = session.scalar(select(UserModel).where(UserModel.email == "investor@example.com"))
    NotificationService(session).notify(
        investor.id, NotificationEvent.ANALYSIS_READY, "BBCA analysis is ready."
    )
    session.commit()

    body = client.get("/notifications", headers=auth_headers).json()
    assert len(body) == 1
    assert body[0]["subject"] == "New analysis available"


def test_the_event_and_context_reach_the_client(client, auth_headers, session) -> None:
    """The interface groups and links on these. Storing them and then not
    serving them would leave it parsing the subject line back into a category."""
    from aidss.db.models import User as UserModel

    investor = session.scalar(select(UserModel).where(UserModel.email == "investor@example.com"))
    NotificationService(session).notify(
        investor.id,
        NotificationEvent.MONITORING_ALERT,
        "Monitoring raised 2 alert(s) for BBCA.",
        context={"count": 2, "tickers": ["BBCA"]},
    )
    session.commit()

    [body] = client.get("/notifications", headers=auth_headers).json()
    assert body["event"] == "monitoring_alert"
    assert body["context"] == {"count": 2, "tickers": ["BBCA"]}


def test_a_read_notification_is_still_findable_in_the_history(
    client, auth_headers, session
) -> None:
    """Marking one read used to delete it from the only endpoint that returned
    it, so "what was that alert an hour ago?" had no answer."""
    from aidss.db.models import User as UserModel

    investor = session.scalar(select(UserModel).where(UserModel.email == "investor@example.com"))
    result = NotificationService(session).notify(
        investor.id, NotificationEvent.REPORT_READY, "Your report is ready."
    )[0]
    session.commit()

    client.post(f"/notifications/{result.notification_id}/read", headers=auth_headers)

    assert client.get("/notifications", headers=auth_headers).json() == []
    history = client.get(
        "/notifications", params={"include_read": True}, headers=auth_headers
    ).json()
    assert [n["id"] for n in history] == [str(result.notification_id)]


def test_the_unread_count_tracks_what_is_unread(client, auth_headers, session) -> None:
    from aidss.db.models import User as UserModel

    investor = session.scalar(select(UserModel).where(UserModel.email == "investor@example.com"))
    service = NotificationService(session)
    first = service.notify(investor.id, NotificationEvent.REPORT_READY, "One.")[0]
    service.notify(investor.id, NotificationEvent.NEWS_INGESTED, "Two.")
    session.commit()

    assert client.get("/notifications/unread-count", headers=auth_headers).json() == {
        "unread": 2
    }

    client.post(f"/notifications/{first.notification_id}/read", headers=auth_headers)
    assert client.get("/notifications/unread-count", headers=auth_headers).json() == {
        "unread": 1
    }


def test_the_unread_count_is_scoped_to_the_caller(client, auth_headers, session) -> None:
    other = User(email="counted@example.com", password_hash=hash_password("correct-horse-b"))
    session.add(other)
    session.flush()
    NotificationService(session).notify(other.id, NotificationEvent.REPORT_READY, "Theirs.")
    session.commit()

    assert client.get("/notifications/unread-count", headers=auth_headers).json() == {
        "unread": 0
    }


# --- Operations overview ---------------------------------------------------


def test_the_overview_counts_what_exists(session, client, auth_headers, analysed) -> None:
    overview = build_overview(session)
    assert overview.inventory["assets"] >= 1
    assert overview.inventory["price_bars"] > 0
    assert overview.inventory["analyses"] >= 1


def test_the_overview_reports_ai_cost_per_agent(session, client, auth_headers, analysed) -> None:
    overview = build_overview(session)
    assert overview.ai_usage["total_tokens"] > 0
    assert "technical_analyzer" in overview.ai_usage["by_agent"]
    assert "estimates" in overview.ai_usage["note"]


def test_a_call_is_counted_once_not_twice(session, client, auth_headers, analysed) -> None:
    """A prompt and its answer are one exchange, not two calls."""
    overview = build_overview(session)
    technical = overview.ai_usage["by_agent"]["technical_analyzer"]
    assert technical["calls"] >= 1
    assert technical["tokens"] > technical["calls"]


def test_success_rate_is_reported_with_its_denominator(
    session, client, auth_headers, analysed
) -> None:
    """"100% success" over two runs is a different claim from over two thousand."""
    overview = build_overview(session)
    assert overview.ingestion["runs"] > 0
    assert overview.ingestion["success_rate"] is not None


def test_an_empty_system_reports_no_success_rate_rather_than_100_percent(session) -> None:
    overview = build_overview(session)
    assert overview.ingestion["runs"] == 0
    assert overview.ingestion["success_rate"] is None


def test_flagged_schedules_appear_under_attention(session, client, auth_headers) -> None:
    from datetime import UTC, datetime

    from aidss.db.models import Asset, ScheduleStatus, TickerNewsSchedule
    from aidss.db.models import User as UserModel

    asset = Asset(ticker="FLAG", exchange="IDX")
    session.add(asset)
    investor = session.scalar(select(UserModel).where(UserModel.email == "investor@example.com"))
    session.flush()

    session.add(
        TickerNewsSchedule(
            user_id=investor.id,
            asset_id=asset.id,
            cron_expression="0 7 * * 1-5",
            status=ScheduleStatus.NEEDS_ATTENTION,
            consecutive_failures=5,
            next_run_at=datetime.now(UTC),
        )
    )
    session.flush()

    overview = build_overview(session)
    assert any(item["kind"] == "news_schedule" for item in overview.attention)


def test_the_overview_is_admin_only(client, auth_headers) -> None:
    assert client.get("/admin/overview", headers=auth_headers).status_code == 403


def test_an_admin_can_read_the_overview(client, admin_headers) -> None:
    response = client.get("/admin/overview", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "inventory" in body
    assert "ai_usage" in body
    assert "market_data" in body["providers"]["registered"]
