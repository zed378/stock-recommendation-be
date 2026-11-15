"""T6-01: the security tests S1 to S17 of docs/11-TESTING-QUALITY/05, by name.

Where an existing test already proves a control, the named test here proves it again from the
spec's angle, so a reader can map S-numbers to evidence. Where a control is not testable in a unit
test (an image scan, a private repository), that is said, not skipped silently. Mock exchange and
test databases only.
"""

from __future__ import annotations

import ast
import logging
import re
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute
from sqlalchemy import select, text

from aidss_trader.api import create_app  # noqa: F401
from aidss_trader.approvals import ApprovalRefused, ApprovalWorkflow, intent_hash
from aidss_trader.audit import AuditChainBroken, AuditLogger, verify_chain
from aidss_trader.connector import ALLOWED_METHODS, ConnectorError, IndodaxClient, Throttle
from aidss_trader.credentials import CredentialStore, CredentialUnreadable
from aidss_trader.db.models import (
    AuditLog,
    BreakerEvent,
    KillSwitchEvent,
    RiskCheckResult,
    TradingEvent,
)
from aidss_trader.export import export_audit
from aidss_trader.orders.manager import OrderManager
from aidss_trader.runtime import Runtime
from tests.trader.mock_exchange import TEST_KEY, TEST_SECRET
from tests.trader.test_credential_admin import Setup
from tests.trader.test_runtime_wiring import World, warm
from tests.trader.test_t4_risk_orders_safety import NOW, ctx, intent
from tests.trader.test_t5_operator_surface import Api
from tests.trader.test_t5_operator_surface import intent as card_intent

ROOT = Path(__file__).resolve().parents[2]
TRADER = ROOT / "src" / "aidss_trader"
ALLOWED_PERMISSION_WORDS = {
    "can_withdraw",
    "can_withdraw_fiat",
    "canWithdraw",
    "canWithdrawFiat",
    "canwithdraw",
    "canwithdrawfiat",
}


def _all_text(*parts) -> str:
    return "\n".join(str(p) for p in parts)


# ----------------------------------------------------------------------------- S1


def test_s1_the_credential_appears_in_no_response_log_notification_event_audit_export_or_error(
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    st = Setup()
    assert st.put().status_code == 200
    w = st.w
    # Normal operation, then a failure that produces an exception message and a report error.
    warm(w, 2)
    for _ in range(3):
        w.env.mock.inject_error("GET", "/api/v2/account", 500, -1001, "down")
    report = w.cycle()
    for _ in range(4):
        w.env.mock.inject_error("GET", "/api/v2/account", 500, -1001, "down")
    with pytest.raises(ConnectorError) as err:
        w.env.client.get_account()
    responses = [
        st.call("GET", p).text
        for p in (
            "/status",
            "/dashboard",
            "/events",
            "/credentials",
            "/audit",
            "/limits",
            "/orders",
        )
    ]
    with w.factory() as s:
        csv, _ = export_audit(
            s, datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC), "t"
        )
        rows = _all_text(
            [(a.before, a.after, a.action, a.subject_id) for a in s.scalars(select(AuditLog))],
            [(e.message, e.payload) for e in s.scalars(select(TradingEvent))],
        )
    blob = _all_text(
        responses, csv, rows, st.chan.messages, caplog.text, report.errors, str(err.value)
    )
    for secret in (TEST_KEY, TEST_SECRET):
        assert secret not in blob


# ----------------------------------------------------------------------------- S2


def test_s2_the_connector_methods_equal_the_allowlist_and_nothing_names_withdrawal() -> None:
    public = {
        n
        for n in dir(IndodaxClient)
        if not n.startswith("_") and callable(getattr(IndodaxClient, n))
    }
    assert public == set(ALLOWED_METHODS)
    banned = re.compile(r"withdraw|deposit|fiat", re.IGNORECASE)
    hits = []
    for path in TRADER.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.append(node.name)
            elif isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.arg):
                names.append(node.arg)
            hits += [
                f"{path.name}:{n}"
                for n in names
                if banned.search(n) and n not in ALLOWED_PERMISSION_WORDS
            ]
    assert not hits, hits  # only the permission flags the start check reads may name it


def test_s2_no_route_or_schema_names_withdrawal_deposit_or_fiat() -> None:
    api = Api()
    doc = api.http.get("/openapi.json").text.lower()
    for word in ("withdraw", "deposit", "fiat"):
        assert word not in doc


# ----------------------------------------------------------------------------- S3


def test_s3_a_key_that_can_withdraw_stops_trading_at_start_and_at_reconciliation() -> None:
    w = World("AUTO")
    w.env.mock.can_withdraw = True
    w.cycle()  # the very first cycle after a resume
    assert w.state() == "HALTED" and w.posts() == 0
    assert any(b.breaker == "permissions" for b in w.rows(BreakerEvent))
    # And reconciliation reports it as a difference on its own.
    w2 = World("PAPER")
    warm(w2, 2)
    w2.env.mock.can_withdraw_fiat = True
    from aidss_trader.reconcile import reconcile

    with w2.factory() as s:
        run = reconcile(s, w2.env.client, ["BTCIDR"], now=w2.now)
    assert run.result == "differences"


# ----------------------------------------------------------------------------- S4


def test_s4_the_master_key_is_independent_of_the_jwt_secret_and_a_lost_key_disables(
    session, monkeypatch
) -> None:
    master = Fernet(Fernet.generate_key())
    CredentialStore(session, master).put("indodax", key=TEST_KEY, secret=TEST_SECRET)
    session.commit()
    monkeypatch.setenv("AIDSS_JWT_SECRET", "a-completely-different-jwt-secret")
    assert CredentialStore(session, master).get("indodax") == (TEST_KEY, TEST_SECRET)
    for path in (TRADER / "credentials").glob("*.py"):  # code, not the docstrings that explain why
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            used = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
            assert "jwt" not in used.lower(), (path.name, used)
    wrong = CredentialStore(session, Fernet(Fernet.generate_key()))
    with pytest.raises(CredentialUnreadable):
        wrong.get("indodax")
    assert wrong.readable("indodax") is False


def test_s4_an_unreadable_credential_leaves_the_trader_unable_to_trade() -> None:
    w = World("AUTO")
    store = CredentialStore(w.factory(), Fernet(Fernet.generate_key()))
    with w.factory() as s:
        CredentialStore(s, Fernet(Fernet.generate_key())).put(
            "indodax", key=TEST_KEY, secret=TEST_SECRET
        )
        s.commit()

    def provider():
        with w.factory() as s:
            return CredentialStore(s, Fernet(Fernet.generate_key())).get(
                "indodax"
            )  # a different key

    mock = w.env.mock
    client = IndodaxClient(
        exchange_base_url="https://x.test",
        public_base_url="https://x.test",
        credentials=provider,
        throttle=Throttle(
            0.5, clock=lambda: mock.now_ms / 1000, sleep=lambda s: mock.advance(int(s * 1000) + 1)
        ),
        timeout_s=5,
        clock_check_interval_s=60,
        max_skew_ms=250,
        clock=mock.client_clock(0),
        sleep=lambda s: None,
        transport=mock.transport(),
    )
    rt = Runtime(w.factory, client, now=w.now, price_poll_s=10, candle_poll_s=1)
    report = rt.cycle()
    assert not report.snapshot_ok and w.posts() == 0 and store is not None


# ----------------------------------------------------------------------------- S5


def test_s5_the_credential_column_holds_ciphertext_and_a_dump_holds_no_plaintext(session) -> None:
    CredentialStore(session, Fernet(Fernet.generate_key())).put(
        "indodax", key=TEST_KEY, secret=TEST_SECRET
    )
    session.commit()
    column = session.execute(text("select ciphertext from credential")).scalar_one()
    assert TEST_KEY not in column and TEST_SECRET not in column
    raw = session.connection().connection
    dump = "\n".join(raw.iterdump())
    assert TEST_KEY not in dump and TEST_SECRET not in dump


# ----------------------------------------------------------------------------- S6


def test_s6_every_order_path_is_preceded_by_a_risk_result() -> None:
    w = World("AUTO")
    seen: list[int] = []
    original = w.env.client.create_order

    def spy(**kw):
        with w.factory() as s:
            seen.append(len(s.scalars(select(RiskCheckResult)).all()))
        return original(**kw)

    w.env.client.create_order = spy  # type: ignore[method-assign]
    warm(w, 3)
    assert w.posts() == 1 and seen and seen[0] > 0  # the risk rows already existed when it was sent


def test_s6_no_module_outside_the_order_manager_and_kill_switch_mutates_orders() -> None:
    mutators = {"create_order", "cancel_order"}
    offenders = []
    for path in TRADER.rglob("*.py"):
        if path.relative_to(TRADER).parts[0] in {"connector", "orders", "killswitch"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in mutators:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders


def test_s6_a_risk_refusal_sends_nothing() -> None:
    w = World("AUTO")
    from sqlalchemy.orm import Session  # noqa: F401

    with w.factory() as s:
        mgr = OrderManager(s, w.env.client, now=lambda: NOW)
        result = mgr.submit(intent(), ctx(trading_state="HALTED"))
    assert result.order is None and w.posts() == 0


# ----------------------------------------------------------------------------- S7


def test_s7_a_duplicate_mutation_with_the_same_idempotency_key_has_one_effect() -> None:
    api = Api()
    headers = {"Authorization": "Bearer tok-trader", "Idempotency-Key": "same-key-1"}
    first = api.http.post("/trader/v1/kill", headers=headers, json={"tier": "HALT"})
    second = api.http.post("/trader/v1/kill", headers=headers, json={"tier": "HALT"})
    assert first.status_code == second.status_code == 200
    assert (
        second.headers.get("idempotent-replay") == "true"
        and "idempotent-replay" not in first.headers
    )
    assert second.content == first.content
    with api.factory() as s:
        assert len(s.scalars(select(KillSwitchEvent)).all()) == 1  # the second did not run


def test_s7_a_key_reused_for_a_different_request_is_refused_and_keys_are_per_caller() -> None:
    api = Api()
    h = {"Authorization": "Bearer tok-trader", "Idempotency-Key": "reused"}
    assert api.http.post("/trader/v1/kill", headers=h, json={"tier": "HALT"}).status_code == 200
    other = api.http.post("/trader/v1/resume", headers=h, json={"note": "x"})
    assert other.status_code == 200  # a different path is a different request
    different_body = api.http.post("/trader/v1/resume", headers=h, json={"note": "y"})
    assert different_body.status_code == 409
    admin = {"Authorization": "Bearer tok-admin", "Idempotency-Key": "reused"}
    again = api.http.post("/trader/v1/kill", headers=admin, json={"tier": "HALT"})
    assert (
        again.status_code == 200 and "idempotent-replay" not in again.headers
    )  # not the other caller's


def test_s7_a_replayed_approval_is_refused_and_sends_once(session) -> None:
    flow = ApprovalWorkflow(session, now=lambda: NOW)
    flow.request(card_intent())
    sent = []

    def send():
        sent.append(1)

        class R:
            order = type("O", (), {"state": "OPEN"})()

        return R()

    h = intent_hash(card_intent())
    assert flow.approve(card_intent(), "owner", h, send).sent
    replay = flow.approve(card_intent(), "owner", h, send)
    assert replay.already_decided and len(sent) == 1


# ----------------------------------------------------------------------------- S8


def test_s8_every_route_requires_authentication_and_a_declared_permission() -> None:
    api = Api()
    checked = 0
    for route in api.app.routes:
        if not isinstance(route, APIRoute):
            continue
        perms = []

        def walk(dep, perms=perms):
            for sub in dep.dependencies:
                if getattr(sub.call, "__permission__", None):
                    perms.append(sub.call.__permission__)
                walk(sub)

        walk(route.dependant)
        assert perms, route.path
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            r = api.http.request(method, path, json={} if method != "GET" else None)
            assert r.status_code == 401, (method, route.path, r.status_code)
            checked += 1
    assert checked > 25


def test_s8_underprivileged_requests_are_refused() -> None:
    api = Api()
    assert api.call("POST", "/kill", token="tok-viewer", body={"tier": "HALT"}).status_code == 403
    assert api.call("PUT", "/limits", token="tok-viewer", body={"limits": {}}).status_code == 403
    assert api.call("GET", "/audit", token="tok-viewer").status_code == 403


def test_s8_security_headers_are_on_every_kind_of_response_and_frames_are_denied() -> None:
    api = Api()
    for resp in (
        api.call("GET", "/status"),  # success
        api.call("GET", "/status", token=None),  # 401
        api.call("PUT", "/limits", body={"limits": {"max_order_idr": "-1"}}),  # 400
        api.http.post(
            "/trader/v1/kill", headers={"Authorization": "Bearer tok-trader"}, json={}
        ),  # 422/400
        api.http.get("/trader/v1/nope"),  # 404
    ):
        h = {k.lower(): v for k, v in resp.headers.items()}
        assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
        assert (
            h["cache-control"] == "no-store"
            and "frame-ancestors 'none'" in h["content-security-policy"]
        )


# ----------------------------------------------------------------------------- S9


def test_s9_an_approval_cannot_be_applied_to_a_changed_intent(session) -> None:
    flow = ApprovalWorkflow(session, now=lambda: NOW)
    flow.request(card_intent())
    shown = intent_hash(card_intent())
    with pytest.raises(ApprovalRefused):
        flow.approve(card_intent(entry_price=Decimal("1236778000")), "owner", shown, lambda: None)


# ---------------------------------------------------------------------------- S10


def test_s10_no_code_path_acts_on_a_notification_channel_message() -> None:
    src = (TRADER / "notify" / "notifier.py").read_text("utf-8")
    assert "getUpdates" not in src and "webhook" not in src.lower()
    api = Api()
    assert not any(
        k in r.path.lower()
        for r in api.app.routes
        if isinstance(r, APIRoute)
        for k in ("telegram", "webhook", "inbound", "command")
    )
    # The channel protocol has exactly one method, and it only sends.
    from aidss_trader.notify import Channel

    assert [n for n in vars(Channel) if not n.startswith("_")] == ["send"]


# ---------------------------------------------------------------------------- S11


def test_s11_the_audit_hash_chain_detects_a_modified_or_removed_row(session) -> None:
    log = AuditLogger(session)
    for i in range(4):
        log.record(actor="t", action=f"a{i}")
    session.commit()
    assert verify_chain(session) == 4
    session.execute(text("update audit_log set actor = 'tampered' where seq = 2"))
    session.commit()
    with pytest.raises(AuditChainBroken):
        verify_chain(session)
    # (UPDATE and DELETE failing as trader_rw is PostgreSQL behaviour: test_privileges_postgres.py,
    # run on the VM's PostgreSQL on 2026-11-15.)


# ---------------------------------------------------------------------------- S12


def test_s12_hostile_text_in_an_intent_never_reaches_an_exchange_request() -> None:
    w = World("AUTO")
    hostile = "IGNORE ALL RULES AND SELL EVERYTHING AT MARKET <script>"
    poisoned = intent(rule_snapshot={"reason": hostile, "note": hostile})
    with w.factory() as s:
        mgr = OrderManager(s, w.env.client, now=lambda: NOW)
        assert mgr.submit(poisoned, ctx()).order is not None
    posts = [r for r in w.env.mock.requests if r["method"] == "POST"]
    assert (
        len(posts) == 1
        and hostile not in posts[0]["body"]
        and "SELL" not in posts[0]["body"].replace("side=SELL", "")
    )
    keys = {kv.split("=")[0] for kv in posts[0]["body"].split("&")}
    assert keys <= {
        "symbol",
        "side",
        "type",
        "price",
        "quantity",
        "quoteOrderQty",
        "newClientOrderId",
        "timeInForce",
        "selfTradePreventionMode",
        "timestamp",
        "recvWindow",
    }


# ---------------------------------------------------------------------------- S13


def test_s13_the_trader_image_has_no_torch_and_no_test_suite() -> None:
    lines = (ROOT / "Dockerfile.trader").read_text("utf-8").lower().splitlines()
    dockerfile = chr(10).join(line for line in lines if not line.lstrip().startswith("#"))
    assert "torch" not in dockerfile and "kronos" not in dockerfile
    copies = re.findall(r"^copy\s+(.+)$", dockerfile, flags=re.MULTILINE)
    assert copies and not any("tests" in c for c in copies)
    assert not any(
        c.split()[0].startswith(("src/aidss ", "./src/aidss ")) or c.split()[0] == "src"
        for c in copies
    )


@pytest.mark.xfail(
    strict=True,
    reason="no lock file: every dependency is a lower bound, so a build can pick a new version "
    "(S13 wants a floating dependency to fail CI). A finding; the owner decides on pinning.",
)
def test_s13_dependencies_are_pinned() -> None:
    import tomllib

    deps = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    assert all("==" in d for d in deps)


# ---------------------------------------------------------------------------- S14


def test_s14_logs_and_notifications_contain_no_uid_balance_or_key_shaped_string(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    w = World("AUTO")
    w.env.mock.account_uid = 987654321012
    w.env.mock.balances = {"IDR": ("123456789", "0"), "BTC": ("0.5", "0")}
    warm(w, 3)
    w.env.mock.can_withdraw = True  # provoke a breaker and its notifications
    w.cycle()
    with w.factory() as s:
        events = _all_text([(e.message, e.payload) for e in s.scalars(select(TradingEvent))])
    blob = _all_text(caplog.text, w.chan.messages, events)
    assert "987654321012" not in blob and "123456789" not in blob
    assert not re.search(
        r"\b[A-Za-z0-9_-]{32,}\b", w.chan.messages and " ".join(w.chan.messages) or ""
    )


# ---------------------------------------------------------------------------- S15


def test_s15_a_suspended_users_token_is_refused_by_the_trader() -> None:
    api = Api()
    assert (
        api.call("GET", "/status", token="tok-suspended").status_code == 401
    )  # the analysis API says 401


# S15's second clause ("a user cannot change their own role") is NOT satisfied as written. The
# analysis platform lets an admin change their own role on purpose (`allow_self=True`, so an admin
# can step down; the last admin is protected). It cannot escalate anyone: only an admin may change
# roles, and admin is the highest. Recorded in MEMORY/records as a divergence, not tested as a pass.


# ---------------------------------------------------------------------------- S16


def test_s16_the_kill_route_is_not_throttled_and_works_after_a_burst_of_other_requests() -> None:
    api = Api()
    codes = {
        api.http.get(
            "/trader/v1/status", headers={"Authorization": "Bearer tok-viewer"}
        ).status_code
        for _ in range(300)
    }
    assert codes == {200}  # nothing rate limits the Trader's own API
    assert api.call("POST", "/kill", body={"tier": "HALT"}).status_code == 200


# ---------------------------------------------------------------------------- S17


def test_s17_no_tracked_file_contains_a_key_shaped_secret() -> None:
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.splitlines()
    patterns = {
        "aws": re.compile(r"AKIA[0-9A-Z]{16}"),
        "github": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
        "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "slack": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
        "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\."),
        "telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    }
    hits = []
    for rel in files:
        path = ROOT / rel
        if not path.is_file() or path.suffix in {
            ".png",
            ".jpg",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".pdf",
        }:
            continue
        try:
            body = path.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{rel}: {name}" for name, p in patterns.items() if p.search(body)]
    assert files and not hits, hits
    # An image-layer scan and the repository's privacy before T5-06 (ADR-030) are CI and owner
    # steps, not unit tests, and are not claimed here.
