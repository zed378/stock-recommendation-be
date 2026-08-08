"""Metrics, structured logging, hardening, and budget governance (Phase 9)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from aidss.api.middleware import SECURITY_HEADERS
from aidss.config import Settings
from aidss.db.models import AIConversation, AIMessage, User
from aidss.main import create_app
from aidss.observability.budget import BudgetState, daily_status, spend_since
from aidss.observability.logging import (
    REDACTED,
    JSONFormatter,
    bind_request,
    clear_request,
    redact,
)
from aidss.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    reset_registry,
)
from aidss.security.passwords import hash_password


@pytest.fixture(autouse=True)
def clean_metrics():
    reset_registry()
    yield
    reset_registry()
    clear_request()


# --- Metrics ---------------------------------------------------------------


def test_a_counter_accumulates_per_label_set() -> None:
    counter = Counter("http_requests_total", "requests")
    counter.inc(route="/a")
    counter.inc(route="/a")
    counter.inc(route="/b")

    assert counter.value(route="/a") == 2
    assert counter.value(route="/b") == 1


def test_label_order_does_not_create_a_second_series() -> None:
    """Otherwise the same measurement splits across two time series."""
    counter = Counter("c", "help")
    counter.inc(method="GET", route="/a")
    counter.inc(route="/a", method="GET")
    assert counter.value(route="/a", method="GET") == 2


def test_a_counter_cannot_decrease() -> None:
    """A counter that goes down makes every rate() over it wrong."""
    with pytest.raises(ValueError, match="cannot decrease"):
        Counter("c", "help").inc(-1)


def test_a_gauge_can_go_both_ways() -> None:
    gauge = Gauge("in_flight", "help")
    gauge.inc(1.0)
    gauge.inc(-1.0)
    assert gauge.value() == 0.0


def test_histogram_buckets_are_cumulative() -> None:
    histogram = Histogram("latency", "help", buckets=(0.1, 1.0, 10.0))
    for value in (0.05, 0.5, 5.0):
        histogram.observe(value)

    rendered = "\n".join(histogram.render())
    assert 'le="0.1"} 1' in rendered
    assert 'le="1.0"} 2' in rendered
    assert 'le="10.0"} 3' in rendered


def test_the_infinity_bucket_equals_the_total_count() -> None:
    """Prometheus rejects an exposition where it does not."""
    histogram = Histogram("latency", "help", buckets=(0.1,))
    histogram.observe(0.05)
    histogram.observe(99.0)

    rendered = "\n".join(histogram.render())
    assert 'le="+Inf"} 2' in rendered
    assert "latency_count" in rendered
    assert "latency_sum" in rendered


def test_the_exposition_declares_help_and_type() -> None:
    registry = MetricsRegistry()
    registry.counter("aidss_test_total", "A test counter").inc()
    rendered = registry.render()

    assert "# HELP aidss_test_total A test counter" in rendered
    assert "# TYPE aidss_test_total counter" in rendered
    assert rendered.endswith("\n")


def test_reusing_a_name_with_a_different_type_is_refused() -> None:
    registry = MetricsRegistry()
    registry.counter("shared", "help")
    with pytest.raises(TypeError, match="already registered"):
        registry.gauge("shared", "help")


def test_label_values_are_escaped() -> None:
    counter = Counter("c", "help")
    counter.inc(route='/a"b')
    assert '\\"' in "\n".join(counter.render())


# --- Redaction -------------------------------------------------------------


def test_sensitive_keys_are_replaced_wholesale() -> None:
    payload = {"email": "a@example.com", "password": "hunter2", "api_key": "sk-abc123"}
    cleaned = redact(payload)

    assert cleaned["email"] == "a@example.com"
    assert cleaned["password"] == REDACTED
    assert cleaned["api_key"] == REDACTED


def test_credentials_inside_free_text_are_stripped() -> None:
    """An exception message quoting a URL is the usual way a secret leaks."""
    assert "sk-abcdef123456" not in redact("call failed with key sk-abcdef123456")
    assert "eyJhbGci" not in redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc")


def test_connection_string_credentials_are_stripped() -> None:
    cleaned = redact("postgresql://aidss:supersecret@localhost:5432/aidss")
    assert "supersecret" not in cleaned
    assert "localhost" in cleaned


def test_redaction_reaches_into_nested_structures() -> None:
    cleaned = redact({"providers": [{"name": "openai", "api_key": "sk-xyz"}]})
    assert cleaned["providers"][0]["api_key"] == REDACTED
    assert cleaned["providers"][0]["name"] == "openai"


def test_ordinary_values_pass_through() -> None:
    assert redact({"count": 5, "ok": True}) == {"count": 5, "ok": True}


# --- Structured logging ----------------------------------------------------


def make_record(message: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord("aidss.test", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_log_records_are_json() -> None:
    payload = json.loads(JSONFormatter().format(make_record("something happened")))
    assert payload["message"] == "something happened"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "aidss.test"


def test_the_request_id_is_attached_to_every_record() -> None:
    """The twelve lines one analysis produces must be pullable back together."""
    bind_request("req-123", user_id="user-456")
    payload = json.loads(JSONFormatter().format(make_record("x")))
    assert payload["request_id"] == "req-123"
    assert payload["user_id"] == "user-456"


def test_extra_fields_are_included_and_redacted() -> None:
    payload = json.loads(
        JSONFormatter().format(make_record("x", route="/assets", api_key="sk-secret"))
    )
    assert payload["route"] == "/assets"
    assert payload["api_key"] == REDACTED


def test_every_credential_setting_is_on_the_redaction_list() -> None:
    """An inventory guard, because the failure mode is silence.

    Adding a provider means adding a credential setting, and the person adding
    it has no reason to think about the logger. If they forget, nothing breaks
    and nothing warns - the key just appears in the first log line that reports
    configuration. So the list is derived from the settings rather than
    maintained beside them.

    The pattern-based redactor would catch some of these in free text anyway,
    but not a value that happens to look ordinary, and not as a field name.
    """
    from aidss.config import Settings
    from aidss.observability.logging import SENSITIVE_KEYS

    credential_fields = {
        name
        for name in Settings.model_fields
        if name.endswith(("_key", "_secret", "_password", "_token"))
    }
    assert credential_fields, "the heuristic matched nothing - it has stopped working"

    missing = credential_fields - SENSITIVE_KEYS
    assert not missing, (
        f"credential settings absent from SENSITIVE_KEYS: {sorted(missing)}. "
        "Add them, or they will be logged in the clear."
    )


def test_a_secret_in_the_message_never_reaches_the_log() -> None:
    payload = json.loads(JSONFormatter().format(make_record("using key sk-abcdef123456")))
    assert "sk-abcdef123456" not in payload["message"]


# --- Middleware ------------------------------------------------------------


def test_security_headers_are_present_on_every_response(client: TestClient) -> None:
    response = client.get("/health")
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


def test_security_headers_are_present_on_an_error_response(client: TestClient) -> None:
    """A 401 needs them as much as a 200 does."""
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_personal_data_responses_are_not_cacheable(client: TestClient, auth_headers) -> None:
    """Portfolio data is personal financial information (Section 26)."""
    response = client.get("/portfolio", headers=auth_headers)
    assert "no-store" in response.headers["Cache-Control"]


def test_market_data_responses_are_cacheable(client: TestClient, auth_headers) -> None:
    response = client.get("/assets", headers=auth_headers)
    assert "Cache-Control" not in response.headers


def test_hsts_is_off_unless_enabled(client: TestClient) -> None:
    """Sent over plain HTTP in development it would break the local server."""
    assert "Strict-Transport-Security" not in client.get("/health").headers


def test_hsts_can_be_enabled() -> None:
    app = create_app(Settings(enable_hsts=True, jwt_secret="test-secret-0123456789abcdef"))
    response = TestClient(app).get("/health")
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]


def test_a_request_id_is_returned_and_honoured(client: TestClient) -> None:
    minted = client.get("/health").headers["X-Request-ID"]
    assert minted

    echoed = client.get("/health", headers={"X-Request-ID": "trace-abc"})
    # An inbound id is kept so a trace spans the gateway and this service.
    assert echoed.headers["X-Request-ID"] == "trace-abc"


def test_requests_are_counted_and_timed(client: TestClient) -> None:
    from aidss.observability.metrics import registry

    client.get("/health")
    rendered = registry().render()
    assert "aidss_http_requests_total" in rendered
    assert "aidss_http_request_duration_seconds" in rendered


def test_metrics_are_labelled_by_route_template_not_by_url() -> None:
    """Labelling by concrete path would mint a series per ticker."""
    from aidss.observability.metrics import registry

    app = create_app(Settings(jwt_secret="test-secret-0123456789abcdef"))
    test_client = TestClient(app)
    test_client.get("/assets/BBCA/candles")
    test_client.get("/assets/TLKM/candles")

    rendered = registry().render()
    assert "{ticker}" in rendered
    assert "BBCA" not in rendered


def test_unmatched_paths_collapse_to_one_label() -> None:
    """Otherwise a scanner probing 404s controls the metrics cardinality."""
    from aidss.observability.metrics import registry

    test_client = TestClient(create_app(Settings(jwt_secret="test-secret-0123456789abcdef")))
    for path in ("/nope-1", "/nope-2", "/nope-3"):
        test_client.get(path)

    rendered = registry().render()
    assert 'route="unmatched"' in rendered
    assert "nope-1" not in rendered


# --- Rate limiting ---------------------------------------------------------


def limited_client(limit: int = 3) -> TestClient:
    app = create_app(Settings(rate_limit_per_minute=limit, jwt_secret="test-secret-0123456789ab"))
    return TestClient(app)


def test_requests_beyond_the_limit_are_refused() -> None:
    client = limited_client(3)
    for _ in range(3):
        assert client.get("/assets").status_code in (200, 401)
    blocked = client.get("/assets")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_health_and_metrics_stay_reachable_while_throttled() -> None:
    """Monitoring must not go blind exactly when it is needed."""
    client = limited_client(1)
    client.get("/assets")
    client.get("/assets")

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_the_limit_is_per_client_not_global() -> None:
    """Users behind one NAT must not share a budget."""
    app = create_app(Settings(rate_limit_per_minute=2, jwt_secret="test-secret-0123456789abcd"))
    client = TestClient(app)

    a = {"Authorization": "Bearer token-a"}
    b = {"Authorization": "Bearer token-b"}
    client.get("/assets", headers=a)
    client.get("/assets", headers=a)

    assert client.get("/assets", headers=a).status_code == 429
    assert client.get("/assets", headers=b).status_code != 429


def test_the_rate_limit_window_slides(monkeypatch) -> None:
    import aidss.api.middleware as middleware

    client = limited_client(2)
    client.get("/assets")
    client.get("/assets")
    assert client.get("/assets").status_code == 429

    real = middleware.time.monotonic
    monkeypatch.setattr(middleware.time, "monotonic", lambda: real() + 61)
    assert client.get("/assets").status_code != 429


def test_a_throttled_response_still_carries_security_headers() -> None:
    client = limited_client(1)
    client.get("/assets")
    blocked = client.get("/assets")
    assert blocked.status_code == 429
    assert blocked.headers["X-Content-Type-Options"] == "nosniff"


# --- Metrics endpoint ------------------------------------------------------


def test_the_metrics_endpoint_uses_the_prometheus_content_type(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "version=0.0.4" in response.headers["content-type"]


def test_the_metrics_endpoint_needs_no_token(client: TestClient) -> None:
    """A scraper that needs auth stops working when auth breaks."""
    assert client.get("/metrics").status_code == 200


def test_no_identifier_appears_in_the_exposition(client: TestClient, auth_headers) -> None:
    client.get("/portfolio", headers=auth_headers)
    body = client.get("/metrics").text
    assert "investor@example.com" not in body
    assert "Bearer" not in body


# --- Budget ----------------------------------------------------------------


@pytest.fixture
def conversation(session) -> AIConversation:
    user = User(email="budget@example.com", password_hash=hash_password("correct-horse-battery"))
    session.add(user)
    session.flush()
    row = AIConversation(user_id=user.id, context_type="test")
    session.add(row)
    session.flush()
    return row


def spend(session, conversation, amount: str, *, hours_ago: int = 1) -> None:
    session.add(
        AIMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="x",
            cost_estimate=Decimal(amount),
            created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        )
    )
    session.flush()


def test_spend_is_read_from_the_audit_trail(session, conversation) -> None:
    """A second counter would eventually disagree with the first."""
    spend(session, conversation, "0.25")
    spend(session, conversation, "0.75")
    total = spend_since(session, datetime.now(UTC) - timedelta(days=1))
    assert total == Decimal("1.00")


def test_spend_outside_the_window_is_excluded(session, conversation) -> None:
    spend(session, conversation, "5.00", hours_ago=48)
    spend(session, conversation, "1.00", hours_ago=2)
    assert spend_since(session, datetime.now(UTC) - timedelta(days=1)) == Decimal("1.00")


def test_no_ceiling_reports_spend_without_a_state(session, conversation) -> None:
    spend(session, conversation, "3.00")
    status = daily_status(session, ceiling=None)
    assert status.state == BudgetState.OK
    assert status.ceiling is None
    assert not status.should_block


def test_a_warning_is_raised_before_the_ceiling(session, conversation) -> None:
    """Someone must hear about it while there is still time to act."""
    spend(session, conversation, "8.50")
    status = daily_status(session, ceiling=10.0, warning_threshold=0.8)
    assert status.state == BudgetState.WARNING
    assert not status.should_block
    assert "85%" in status.message


def test_reaching_the_ceiling_blocks(session, conversation) -> None:
    """A budget that only reports overspending is a report."""
    spend(session, conversation, "10.00")
    status = daily_status(session, ceiling=10.0)
    assert status.state == BudgetState.EXCEEDED
    assert status.should_block


def test_spend_below_the_threshold_is_fine(session, conversation) -> None:
    spend(session, conversation, "1.00")
    status = daily_status(session, ceiling=10.0)
    assert status.state == BudgetState.OK
    assert status.utilisation == pytest.approx(0.1)


def test_the_budget_endpoint_is_admin_only(client: TestClient, auth_headers) -> None:
    assert client.get("/admin/budget", headers=auth_headers).status_code == 403


def test_an_admin_can_read_the_budget(client: TestClient, admin_headers) -> None:
    body = client.get("/admin/budget", headers=admin_headers).json()
    assert body["state"] in {"ok", "warning", "exceeded"}
    assert body["message"]


def test_library_chatter_is_held_at_warning() -> None:
    """`httpx` logs a line per outbound request. One monitoring pass over a
    watchlist of thirteen is thirteen lines a minute for ever - about twenty
    thousand a day of "GET ... 200 OK" that bury the lines saying what the
    platform actually did.
    """
    import logging

    from aidss.observability.logging import NOISY_LIBRARIES, configure_logging

    configure_logging("INFO")
    for name in NOISY_LIBRARIES:
        assert logging.getLogger(name).level == logging.WARNING, name


def test_the_quieting_survives_a_debug_root() -> None:
    """DEBUG is what an operator reaches for when hunting something specific,
    which is exactly when the flood is least welcome."""
    import logging

    from aidss.observability.logging import configure_logging

    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING


def test_a_failing_request_is_still_reported() -> None:
    """WARNING, not silence: turning a library off entirely trades one
    blindness for another."""
    import logging

    from aidss.observability.logging import configure_logging

    configure_logging("INFO")
    assert logging.getLogger("httpx").isEnabledFor(logging.WARNING)
    assert logging.getLogger("httpx").isEnabledFor(logging.ERROR)
