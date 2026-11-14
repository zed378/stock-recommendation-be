"""Credential administration: store, test, rotate, remove. Mock exchange and a recording fake
Telegram only; every key below is generated in this file and is not a real one."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from aidss_trader.api import ApiContext, create_app
from aidss_trader.auth import TokenVerifier
from aidss_trader.auth.stepup import StepUp
from aidss_trader.connector import IndodaxClient, Throttle
from aidss_trader.credentials import CredentialStore
from aidss_trader.db.models import AuditLog, Credential, TradingEvent
from aidss_trader.killswitch import KillSwitch
from aidss_trader.notify import Notifier, RecordingChannel
from aidss_trader.promotion import Thresholds
from tests.trader.mock_exchange import TEST_KEY, TEST_SECRET
from tests.trader.test_runtime_wiring import World

TELEGRAM_TOKEN = "123456789:AAEtest_token_generated_in_this_test_only"
CHAT = "424242"
EMAILS = {"o@x": "tok", "a@x": "tok-admin"}
USERS = {"tok": ("u1", "trader"), "tok-admin": ("u2", "admin"), "tok-viewer": ("u3", "viewer")}


class Setup:
    def __init__(self, *, master_key: bool = True, exchange: bool = True) -> None:
        self.w = World("PAPER", configured=False)
        self.fernet = Fernet(Fernet.generate_key()) if master_key else None
        self.sent: list[tuple[str, str, str]] = []
        self.telegram_fails = False
        env = self.w.env

        def candidate(key: str, secret: str) -> IndodaxClient | None:
            if not exchange:
                return None
            return IndodaxClient(
                exchange_base_url="https://exchange.test",
                public_base_url="https://public.test",
                credentials=lambda: (key, secret),
                throttle=Throttle(0.5, clock=lambda: env.mock.now_ms / 1000, sleep=lambda s: None),
                timeout_s=5,
                clock_check_interval_s=60,
                max_skew_ms=250,
                clock=env.mock.client_clock(0),
                sleep=lambda s: None,
                transport=env.mock.transport(),
            )

        def send(token: str, chat: str, text: str) -> None:
            if self.telegram_fails:
                raise RuntimeError(f"failed for https://api.telegram.org/bot{token}/sendMessage")
            self.sent.append((token, chat, text))

        def me(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/auth/login":
                email = json.loads(req.content)["email"]
                return httpx.Response(200, json={"access_token": EMAILS[email]})
            who = USERS.get(req.headers.get("authorization", "")[7:])
            if who is None:
                return httpx.Response(401)
            return httpx.Response(200, json={"id": who[0], "role": who[1]})

        t = httpx.MockTransport(me)
        verifier = TokenVerifier("https://a.test", timeout_s=2, transport=t)
        self.chan = RecordingChannel()
        ctx = ApiContext(
            session_factory=self.w.factory,
            verifier=verifier,
            stepup=lambda s: StepUp(s, "https://a.test", verifier, transport=t),
            notifier=lambda s: Notifier(s, self.chan),
            killswitch=lambda s: KillSwitch(s, env.client),
            submit_approved=self.w.runtime.submit_approved,
            thresholds=lambda: Thresholds(),
            freshness=self.w.runtime.freshness,
            credentials=lambda s: CredentialStore(s, self.fernet) if self.fernet else None,
            exchange_client_for=candidate,
            stored_exchange_client=lambda: env.client,
            telegram_send=send,
        )
        self.client = TestClient(create_app(ctx))
        self.n = 0

    def call(self, method, path, body=None, token="tok", **headers):
        self.n += 1
        h = {"Authorization": f"Bearer {token}", "Idempotency-Key": f"k{self.n}", **headers}
        return self.client.request(method, "/trader/v1" + path, json=body, headers=h)

    def grant(self, token="tok") -> str:
        email = "a@x" if token == "tok-admin" else "o@x"
        body = {"email": email, "password": "pw", "scope": "CREDENTIALS"}
        return self.call("POST", "/stepup", body, token).json()["data"]["grant"]

    def put(self, kind="indodax", key=TEST_KEY, secret=TEST_SECRET, grant=True, token="tok"):
        extra = {"X-Step-Up": self.grant(token)} if grant else {}
        return self.call(
            "PUT", f"/credentials/{kind}", {"key": key, "secret": secret}, token, **extra
        )

    def rows(self, model):
        with self.w.factory() as s:
            return list(s.scalars(select(model)))

    def active(self, kind="indodax"):
        return [c for c in self.rows(Credential) if c.kind == kind and c.active]


@pytest.fixture
def st() -> Setup:
    return Setup()


# ----------------------------------------------------------------------- store


def test_a_valid_key_is_tested_then_stored_encrypted_and_shown_masked(st) -> None:
    assert st.put(grant=False).status_code == 403  # storing a key needs a step-up
    r = st.put()
    assert r.status_code == 200
    data = r.json()["data"]
    assert (
        data["configured"] is True
        and data["hint"] == TEST_KEY[-4:]
        and data["last_test_ok"] is True
    )
    assert data["readable"] is True
    row = st.active()[0]
    assert TEST_KEY not in row.ciphertext and TEST_SECRET not in row.ciphertext
    listed = st.call("GET", "/credentials").json()["data"]
    assert listed["available"] is True
    assert {i["kind"]: i["configured"] for i in listed["items"]} == {
        "indodax": True,
        "telegram": False,
    }


def test_neither_the_key_nor_the_secret_appears_anywhere_it_could_leak(st, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    responses = [
        st.put().text,
        st.call("GET", "/credentials").text,
        st.call("POST", "/credentials/indodax/test").text,
        st.put(key=TEST_KEY, secret="short").text,  # refused as invalid
        st.call("PUT", "/credentials/indodax", {"key": TEST_KEY}).text,  # missing field: a 422
    ]
    leaky = [TEST_KEY, TEST_SECRET]
    for text in responses:
        assert not any(x in text for x in leaky), text
    blob = " ".join(str(a.before) + str(a.after) + a.action for a in st.rows(AuditLog))
    blob += " ".join(str(e.payload) + e.message for e in st.rows(TradingEvent))
    blob += " ".join(st.chan.messages) + caplog.text
    assert not any(x in blob for x in leaky)


def test_a_validation_error_never_echoes_what_was_submitted(st) -> None:
    r = st.call("PUT", "/credentials/indodax", {"secret": "SENTINEL-SECRET-VALUE-123"})
    assert r.status_code == 422 and "SENTINEL-SECRET-VALUE-123" not in r.text
    assert "key" in r.json()["error"]["message"]


def test_storing_writes_an_audit_row_and_a_notification_without_the_value(st) -> None:
    st.put()
    actions = [a.action for a in st.rows(AuditLog)]
    assert "credential.store" in actions
    assert any(e.kind == "credential_changed" for e in st.rows(TradingEvent))
    assert any("credential changed" in m for m in st.chan.messages)


# ------------------------------------------------------------------ refusals


def test_a_key_the_exchange_rejects_is_refused_and_not_stored(st) -> None:
    r = st.put(key="not-a-real-key-at-all", secret="not-a-real-secret-at-all")
    assert r.status_code == 422 and r.json()["error"]["code"] == "credential_refused"
    assert st.active() == []
    assert any(a.action == "credential.refused" for a in st.rows(AuditLog))


def test_a_key_that_can_withdraw_is_never_stored(st) -> None:
    st.w.env.mock.can_withdraw = True
    r = st.put()
    assert r.status_code == 422 and "withdraw" in r.json()["error"]["message"]
    assert st.active() == []
    st.w.env.mock.can_withdraw = False
    st.w.env.mock.can_withdraw_fiat = True
    assert st.put().status_code == 422 and st.active() == []


def test_a_key_that_cannot_trade_is_refused(st) -> None:
    st.w.env.mock.keys[TEST_KEY]["can_trade"] = False
    r = st.put()
    assert r.status_code == 422 and "trade" in r.json()["error"]["message"]
    assert st.active() == []


def test_with_no_exchange_configured_a_key_cannot_be_stored_untested() -> None:
    s = Setup(exchange=False)
    r = s.put()
    assert r.status_code == 422 and "cannot be tested" in r.json()["error"]["message"]
    assert s.active() == []


def test_without_the_master_key_credentials_are_unavailable_not_silently_empty() -> None:
    s = Setup(master_key=False)
    assert s.call("GET", "/credentials").json()["data"] == {"available": False, "items": []}
    r = s.put()
    assert r.status_code == 503 and r.json()["error"]["code"] == "master_key_unavailable"


def test_malformed_credentials_are_refused_before_any_test(st) -> None:
    for kind, key, secret in (
        ("indodax", "short", "short"),
        ("indodax", "has space in key", "x" * 20),
        ("telegram", "not-a-token", "12345"),
        ("telegram", TELEGRAM_TOKEN, "not a chat id"),
        ("withdrawal", "x" * 20, "y" * 20),
    ):
        r = st.put(kind, key, secret)
        assert r.status_code == 400, (kind, key)
    assert st.rows(Credential) == []


# ------------------------------------------------------------------ rotation


def test_rotation_swaps_atomically_and_a_failed_rotation_keeps_the_old_key(st) -> None:
    st.put()
    first = st.active()[0].id
    st.w.env.mock.keys["second-key-generated-in-this-test-file"] = {
        "secret": "second-secret-generated-in-this-test-file",
        "can_trade": True,
    }
    ok = st.put(
        key="second-key-generated-in-this-test-file",
        secret="second-secret-generated-in-this-test-file",
    )
    assert ok.status_code == 200
    active = st.active()
    assert len(active) == 1 and active[0].id != first  # never zero, never two
    retired = [c for c in st.rows(Credential) if c.id == first][0]
    assert retired.active is False and retired.retired_at is not None
    bad = st.put(key="third-key-the-exchange-rejects", secret="third-secret-the-exchange-rejects")
    assert bad.status_code == 422
    assert [c.id for c in st.active()] == [active[0].id]  # still the second key


# ---------------------------------------------------------------------- test


def test_testing_the_stored_key_records_the_outcome_and_places_no_order(st) -> None:
    st.put()
    posts_before = st.w.posts()
    r = st.call("POST", "/credentials/indodax/test")
    assert r.status_code == 200 and r.json()["data"]["last_test_ok"] is True
    assert st.w.posts() == posts_before  # a test never places or cancels an order
    st.w.env.mock.can_withdraw = True  # the key's permissions changed at the exchange
    bad = st.call("POST", "/credentials/indodax/test").json()["data"]
    assert bad["last_test_ok"] is False and "withdraw" in bad["reason"]
    assert st.call("GET", "/credentials").json()["data"]["items"][0]["last_test_ok"] is False


def test_a_credential_the_master_key_can_no_longer_read_is_reported_not_hidden(st) -> None:
    st.put()
    st.fernet = Fernet(Fernet.generate_key())  # the master key changed
    r = st.call("POST", "/credentials/indodax/test")
    assert r.status_code == 409 and r.json()["error"]["code"] == "credential_unreadable"
    item = st.call("GET", "/credentials").json()["data"]["items"][0]
    assert item["configured"] is True and item["readable"] is False


def test_testing_with_nothing_stored_is_a_not_found(st) -> None:
    assert st.call("POST", "/credentials/indodax/test").status_code == 404
    assert st.call("POST", "/credentials/nope/test").status_code == 404


# -------------------------------------------------------------------- remove


def test_removing_the_key_needs_a_step_up_wipes_it_and_halts_trading(st) -> None:
    st.put()
    assert st.call("DELETE", "/credentials/indodax").status_code == 403
    r = st.call("DELETE", "/credentials/indodax", **{"X-Step-Up": st.grant()})
    assert r.status_code == 200 and r.json()["data"]["configured"] is False
    assert st.active() == []
    rows = st.rows(Credential)
    assert rows and all(c.ciphertext == "" for c in rows)  # the row stays, emptied
    assert (
        st.call("GET", "/trader/v1/status".replace("/trader/v1", "")).json()["data"][
            "trading_state"
        ]
        == "HALTED"
    )
    assert any(a.action == "credential.remove" for a in st.rows(AuditLog))
    again = st.call("DELETE", "/credentials/indodax", **{"X-Step-Up": st.grant()})
    assert again.status_code == 404


# -------------------------------------------------------------------- telegram


def test_telegram_is_tested_by_sending_one_harmless_message_and_stored(st) -> None:
    r = st.put("telegram", TELEGRAM_TOKEN, CHAT)
    assert r.status_code == 200 and r.json()["data"]["last_test_ok"] is True
    assert st.sent == [(TELEGRAM_TOKEN, CHAT, "AIDSS Trader: test message. Nothing needs doing.")]
    assert TELEGRAM_TOKEN not in r.text
    assert CredentialStore(next(iter([None])) if False else _session(st), st.fernet).get(
        "telegram"
    ) == (TELEGRAM_TOKEN, CHAT)


def _session(st):
    return st.w.factory()


def test_a_telegram_failure_is_refused_without_the_url_that_carries_the_token(st) -> None:
    st.telegram_fails = True
    r = st.put("telegram", TELEGRAM_TOKEN, CHAT)
    assert r.status_code == 422 and TELEGRAM_TOKEN not in r.text
    assert st.active("telegram") == []


# ----------------------------------------------------------------- permissions


def test_credential_changes_need_the_permission_and_a_viewer_sees_only_the_mask(st) -> None:
    st.put()
    assert st.put(token="tok-viewer", grant=False).status_code == 403
    assert st.call("DELETE", "/credentials/indodax", token="tok-viewer").status_code == 403
    assert st.call("POST", "/credentials/indodax/test", token="tok-viewer").status_code == 403
    view = st.call("GET", "/credentials", token="tok-viewer")
    assert view.status_code == 200 and TEST_KEY not in view.text and TEST_SECRET not in view.text
    assert st.put(token="tok-admin").status_code == 200  # admin holds the permission (ADR-048)
