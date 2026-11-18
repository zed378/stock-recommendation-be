"""Connector contract tests against the SYNTHETIC mock (docs/11-TESTING-QUALITY/02).

These prove the Trader's handling, not the exchange's behaviour: every response
here was shaped from Indodax's documentation, and nothing has been observed live
(T2-07 is the owner-led check).
"""

from __future__ import annotations

import ast
import logging
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aidss_trader.connector import (
    ALLOWED_METHODS,
    ConnectorError,
    ErrorClass,
    IndodaxClient,
    Throttle,
    TokenBucket,
    canonical,
    fmt,
)
from aidss_trader.connector.errors import classify
from tests.trader.mock_exchange import TEST_KEY, TEST_SECRET, MockExchange

EXCHANGE = "https://exchange.test"
PUBLIC = "https://public.test"


class Env:
    """One time source shared by the mock, the throttle, and the client."""

    def __init__(self, *, skew_ms: int = 0, credentials=True, headroom: float = 0.5, **kw) -> None:
        self.mock = MockExchange()
        self.sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)
            self.mock.advance(int(seconds * 1000) + 1)

        self.provided = 0

        def provider() -> tuple[str, str]:
            self.provided += 1
            return TEST_KEY, TEST_SECRET

        self.client = IndodaxClient(
            exchange_base_url=EXCHANGE,
            public_base_url=PUBLIC,
            credentials=provider if credentials else None,
            throttle=Throttle(headroom, clock=lambda: self.mock.now_ms / 1000, sleep=sleep),
            timeout_s=5,
            clock_check_interval_s=60,
            max_skew_ms=250,
            clock=self.mock.client_clock(skew_ms),
            sleep=sleep,
            transport=self.mock.transport(),
            **kw,
        )


@pytest.fixture
def env() -> Env:
    return Env()


# ------------------------------------------------------------- public: success


def test_server_time_pairs_and_increments_parse_to_decimal(env: Env) -> None:
    assert env.client.get_server_time() == env.mock.now_ms
    pair = env.client.get_pairs()[0]
    assert pair.pair == "BTCIDR" and pair.ticker_id == "btc_idr"
    assert pair.quantity_increment == Decimal("0.00000001")
    assert pair.min_base_idr == Decimal("50000") and isinstance(pair.min_traded_qty, Decimal)
    assert env.client.get_price_increments() == {"btc_idr": Decimal("1000")}


@pytest.mark.parametrize("as_strings", [False, True])
def test_ohlc_accepts_both_documented_number_forms(env: Env, as_strings: bool) -> None:
    """D12: the docs show numbers in one place and strings in another."""
    env.mock.candle_numbers_as_strings = as_strings
    env.mock.candles[("BTCIDR", "240")] = [
        (1_700_000_000, "100", "110", "90", "105", "12.5"),
        (1_700_014_400, "105", "120", "100", "118", "8"),
    ]
    got = env.client.get_ohlc("btcidr", "4H", 1_700_000_000, 1_700_100_000)
    assert [c.close for c in got] == [Decimal("105"), Decimal("118")]
    assert all(isinstance(c.volume, Decimal) for c in got)
    assert got[0].open_time.tzinfo is not None
    assert env.mock.requests[-1]["query"].count("tf=240") == 1  # 4H maps to "240"


def test_ohlc_rejects_an_unsupported_timeframe(env: Env) -> None:
    with pytest.raises(ValueError):
        env.client.get_ohlc("BTCIDR", "5m", 0, 1)  # the endpoint has no 5 minute timeframe


def test_prices_and_book_tickers_single_and_multi_symbol(env: Env) -> None:
    assert env.client.get_last_prices(["btc_idr"]) == {"BTCIDR": Decimal("1236777000")}
    assert env.client.get_last_prices() == {"BTCIDR": Decimal("1236777000")}
    book = env.client.get_book_tickers(["BTCIDR"])["BTCIDR"]
    assert book.bid_price < book.ask_price


# ------------------------------------------------------------- signing & auth


def test_account_is_signed_and_does_not_leak_the_account_id(env: Env) -> None:
    acct = env.client.get_account()
    assert acct.can_trade and not acct.can_withdraw and not acct.can_withdraw_fiat
    assert acct.balances["BTC"] == (Decimal("1"), Decimal("0"))
    assert not hasattr(acct, "uid") and "uid" not in repr(acct)


def test_a_wrong_secret_is_an_auth_error_and_never_echoes_it(env: Env) -> None:
    env.mock.keys[TEST_KEY]["secret"] = "a-different-secret"
    with pytest.raises(ConnectorError) as exc:
        env.client.get_account()
    assert exc.value.error_class is ErrorClass.AUTH
    assert TEST_SECRET not in str(exc.value) and TEST_KEY not in str(exc.value)


def test_unknown_key_is_auth_and_missing_credentials_never_send_a_signed_request() -> None:
    env = Env()
    env.mock.keys.clear()
    with pytest.raises(ConnectorError) as exc:
        env.client.get_account()
    assert exc.value.error_class is ErrorClass.AUTH

    bare = Env(credentials=False)
    with pytest.raises(ConnectorError) as exc2:
        bare.client.get_account()
    assert exc2.value.error_class is ErrorClass.AUTH
    assert not [r for r in bare.mock.requests if r["path"] == "/api/v2/account"]


def test_the_secret_is_fetched_per_signature_and_not_stored(env: Env) -> None:
    env.client.get_account()
    env.client.get_open_orders()
    assert env.provided == 2
    assert TEST_SECRET not in repr(vars(env.client)) and TEST_KEY not in repr(vars(env.client))


def test_no_credential_or_signature_appears_in_logs(env: Env, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    env.client.get_account()
    sign = env.mock.requests[-1]["headers"]["sign"]
    text = caplog.text
    assert TEST_SECRET not in text and TEST_KEY not in text and sign not in text


def test_trade_permission_failure_is_permission_class(env: Env) -> None:
    env.mock.keys[TEST_KEY]["can_trade"] = False
    with pytest.raises(ConnectorError) as exc:
        env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            client_order_id="a1",
            price=Decimal("1000"),
            quantity=Decimal("0.001"),
        )
    assert exc.value.error_class is ErrorClass.PERMISSION


# ---------------------------------------------------------------------- clock


def test_clock_skew_beyond_tolerance_halts_before_any_signed_request() -> None:
    env = Env(skew_ms=1500)  # 1.5 s ahead: Indodax would reject at 1 s
    with pytest.raises(ConnectorError) as exc:
        env.client.get_account()
    assert exc.value.error_class is ErrorClass.CLOCK_SKEW
    assert {r["path"] for r in env.mock.requests} == {"/api/server_time"}  # nothing was signed


def _stale_server_time(env: Env, stale: set[int], readings: int = 5) -> None:
    """Indodax serves server_time through caches; some readings come back about 1 s old.
    `stale` holds the 1-based readings (in order) that are a second behind."""
    for n in range(1, readings + 1):
        behind = 1000 if n in stale else 0
        env.mock.inject(
            "GET",
            "/api/server_time",
            lambda behind=behind: httpx.Response(
                200, json={"timezone": "UTC", "server_time": env.mock.now_ms - behind}
            ),
        )


def test_a_minority_of_stale_readings_does_not_halt() -> None:
    env = Env(skew_ms=0)
    _stale_server_time(env, {2, 4})  # 2 of 5 readings are a second old
    assert abs(env.client.check_clock()) <= 250
    env.client.get_account()


def test_a_majority_of_stale_or_skewed_readings_still_halts() -> None:
    env = Env(skew_ms=0)
    # 3 of 5 stale in the first measurement AND in the re-measurement: the median is a second off
    # twice in a row.
    _stale_server_time(env, {1, 2, 3, 6, 7, 8}, readings=10)
    with pytest.raises(ConnectorError) as exc:
        env.client.check_clock()
    assert exc.value.error_class is ErrorClass.CLOCK_SKEW and "median of 5" in str(exc.value)


def test_one_bad_measurement_is_measured_again_before_it_halts() -> None:
    env = Env(skew_ms=0)
    _stale_server_time(env, {1, 2, 3}, readings=5)  # first measurement bad, the second is clean
    assert abs(env.client.check_clock()) <= 250


def test_small_skew_within_the_limit_is_accepted() -> None:
    env = Env(skew_ms=100)
    assert env.client.check_clock() in range(-110, -90)  # measured offset ~ -100 ms
    env.client.get_account()


# ------------------------------------------------------------- failure shapes


def test_read_is_retried_on_timeout_then_surfaces_timeout(env: Env) -> None:
    for _ in range(3):
        env.mock.inject_timeout("GET", "/api/pairs")
    with pytest.raises(ConnectorError) as exc:
        env.client.get_pairs()
    assert exc.value.error_class is ErrorClass.TIMEOUT and exc.value.outcome_unknown is False
    assert len([r for r in env.mock.requests if r["path"] == "/api/pairs"]) == 3  # 1 + 2 retries


def test_a_read_recovers_after_a_transient_failure(env: Env) -> None:
    env.mock.inject_error("GET", "/api/pairs", 503, -1001, "Internal error")
    assert env.client.get_pairs()


def test_rate_limit_from_the_exchange_is_surfaced_and_a_write_is_not_retried(env: Env) -> None:
    env.mock.inject_error("POST", "/api/v2/order", 429, -1003, "Too many requests.")
    with pytest.raises(ConnectorError) as exc:
        env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            client_order_id="a1",
            price=Decimal("1000"),
            quantity=Decimal("0.001"),
        )
    assert exc.value.error_class is ErrorClass.RATE_LIMIT
    assert len([r for r in env.mock.requests if r["path"] == "/api/v2/order"]) == 1


@pytest.mark.parametrize("failure", ["timeout", "5xx"])
def test_create_order_outcome_is_unknown_and_sent_exactly_once(env: Env, failure: str) -> None:
    """FR-T14, ADR-024: after a timeout or 5xx on create, never re-send."""
    if failure == "timeout":
        env.mock.inject_timeout("POST", "/api/v2/order")
    else:
        env.mock.inject_error("POST", "/api/v2/order", 502, -1001, "Internal error")
    with pytest.raises(ConnectorError) as exc:
        env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            client_order_id="intent-1",
            price=Decimal("1000"),
            quantity=Decimal("0.001"),
        )
    assert exc.value.outcome_unknown is True
    assert len([r for r in env.mock.requests if r["path"] == "/api/v2/order"]) == 1


def test_malformed_bodies_are_malformed_not_defaults(env: Env) -> None:
    env.mock.inject("GET", "/api/pairs", lambda: httpx.Response(200, content="<html>"))
    with pytest.raises(ConnectorError) as exc:
        env.client.get_pairs()
    assert exc.value.error_class is ErrorClass.MALFORMED

    env.mock.inject("GET", "/api/server_time", lambda: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(ConnectorError) as exc2:
        env.client.get_server_time()
    assert exc2.value.error_class is ErrorClass.MALFORMED and "server_time" in str(exc2.value)


def test_an_unrecognised_order_status_halts_instead_of_being_guessed(env: Env) -> None:
    env.mock.orders[1] = {
        "id": 1,
        "full": "btcidr-limit-1",
        "client": "x",
        "symbol": "BTCIDR",
        "side": "BUY",
        "type": "LIMIT",
        "price": "1",
        "orig": "1",
        "executed": "0",
        "status": "FILL",
        "time": 0,
        "visible_at": 0,
    }  # the WebSocket spelling (D5)
    with pytest.raises(ConnectorError) as exc:
        env.client.get_order("BTCIDR", order_id=1)
    assert exc.value.error_class is ErrorClass.MALFORMED


@pytest.mark.parametrize("code", [1109, -1109, "1109"])
def test_error_codes_are_matched_with_or_without_the_minus_sign(code) -> None:
    assert classify(400, code) is ErrorClass.VALIDATION  # D17


def test_an_unknown_code_is_never_treated_as_success_or_retryable() -> None:
    assert classify(400, 99999) is ErrorClass.MALFORMED
    assert (
        classify(502, None) is ErrorClass.UNAVAILABLE
        and classify(429, None) is ErrorClass.RATE_LIMIT
    )


# --------------------------------------------------------------------- orders


def _limit(env: Env, client_id: str = "intent-1", **kw):
    return env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        client_order_id=client_id,
        price=Decimal("1236777000"),
        quantity=Decimal("0.001"),
        time_in_force="MOC",
        stp_mode="EXPIRE_TAKER",
        **kw,
    )


def test_create_limit_order_sends_the_documented_parameters(env: Env) -> None:
    order = _limit(env)
    assert order.client_order_id == "intent-1" and order.order_id and order.full_order_id
    assert order.price == Decimal("1236777000") and order.executed_qty == 0
    body = env.mock.requests[-1]["body"]
    for part in (
        "symbol=BTCIDR",
        "side=BUY",
        "type=LIMIT",
        "newClientOrderId=intent-1",
        "timeInForce=MOC",
        "selfTradePreventionMode=EXPIRE_TAKER",
        "quantity=0.001",
    ):
        assert part in body
    assert "e+" not in body.lower()  # no exponent notation, ever


def test_a_duplicate_client_order_id_is_rejected_and_not_retried_with_a_new_id(env: Env) -> None:
    _limit(env)
    with pytest.raises(ConnectorError) as exc:
        _limit(env)
    assert exc.value.error_class is ErrorClass.REJECTED
    assert len(env.mock.orders) == 1


def test_too_much_quantity_precision_is_a_validation_error(env: Env) -> None:
    with pytest.raises(ConnectorError) as exc:
        env.client.create_order(
            symbol="BTCIDR",
            side="BUY",
            order_type="LIMIT",
            client_order_id="p1",
            price=Decimal("1000"),
            quantity=Decimal("0.0000000001"),
        )
    assert exc.value.error_class is ErrorClass.VALIDATION


def test_insufficient_balance_is_rejected(env: Env) -> None:
    env.mock.balances["IDR"] = ("1", "0")
    with pytest.raises(ConnectorError) as exc:
        _limit(env)
    assert exc.value.error_class is ErrorClass.REJECTED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_type": "STOP_LIMIT"},  # never attempted (ADR-007)
        {"side": "HOLD"},
        {"client_order_id": "has space"},
        {"client_order_id": "x" * 37},
        {"time_in_force": "FOK"},  # listed for MARKET in the enums, not for Create Order (D4)
        {"order_type": "MARKET", "side": "BUY", "quantity": Decimal("1"), "price": None},
        {"order_type": "LIMIT", "price": None},
    ],
)
def test_invalid_orders_are_refused_before_anything_is_sent(env: Env, kwargs) -> None:
    base = dict(
        symbol="BTCIDR",
        side="BUY",
        order_type="LIMIT",
        client_order_id="ok-1",
        price=Decimal("1000"),
        quantity=Decimal("1"),
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        env.client.create_order(**base)
    assert not [r for r in env.mock.requests if r["path"] == "/api/v2/order"]


def test_buy_market_uses_quote_order_qty_and_fills(env: Env) -> None:
    order = env.client.create_order(
        symbol="BTCIDR",
        side="BUY",
        order_type="MARKET",
        client_order_id="m1",
        quote_order_qty=Decimal("100000"),
    )
    assert "quoteOrderQty=100000" in env.mock.requests[-1]["body"]
    assert "quantity=" not in env.mock.requests[-1]["body"].replace("quoteOrderQty", "")
    assert order.order_id


def test_a_freshly_accepted_order_may_not_be_visible_yet(env: Env) -> None:
    """The docs warn about this; the UNKNOWN-resolution path depends on handling it."""
    env.mock.visibility_lag_ms = 40_000  # longer than the 30 s UNKNOWN window (ADR-042)
    order = _limit(env)
    with pytest.raises(ConnectorError) as exc:
        env.client.get_order("BTCIDR", client_order_id="intent-1")
    assert exc.value.error_class is ErrorClass.NOT_FOUND
    env.mock.advance(41_000)
    assert env.client.get_order("BTCIDR", order_id=order.order_id).status == "NEW"


def test_get_order_takes_exactly_one_identifier(env: Env) -> None:
    with pytest.raises(ValueError):
        env.client.get_order("BTCIDR", order_id=1, client_order_id="x")
    with pytest.raises(ValueError):
        env.client.get_order("BTCIDR")


def test_cancel_and_not_found(env: Env) -> None:
    order = _limit(env)
    assert env.client.cancel_order("BTCIDR", order_id=order.order_id).order_id == order.order_id
    assert env.client.get_order("BTCIDR", order_id=order.order_id).status == "CANCELLED"
    with pytest.raises(ConnectorError) as exc:
        env.client.cancel_order("BTCIDR", order_id=999999)
    assert exc.value.error_class is ErrorClass.NOT_FOUND


def test_cancel_is_never_retried_on_timeout(env: Env) -> None:
    order = _limit(env)
    env.mock.inject_timeout("DELETE", "/api/v2/order")
    with pytest.raises(ConnectorError) as exc:
        env.client.cancel_order("BTCIDR", order_id=order.order_id)
    assert exc.value.outcome_unknown is True
    assert len([r for r in env.mock.requests if r["method"] == "DELETE"]) == 1


def test_partial_fill_then_history_and_trades(env: Env) -> None:
    order = _limit(env)
    env.mock.fill(order.order_id, "0.0004")
    assert env.client.get_open_orders()[0].status == "PARTIALLY_FILLED"
    env.mock.fill(order.order_id, "0.0006")
    assert env.client.get_open_orders() == []
    history = env.client.get_order_history("BTCIDR")
    assert history[0].status == "FILLED" and history[0].executed_qty == Decimal("0.001")
    trades = env.client.get_my_trades("BTCIDR")
    assert len(trades) == 2 and trades[0].commission == Decimal("468")
    assert trades[0].full_order_id == order.full_order_id  # myTrades uses the full id (D8)


@pytest.mark.parametrize("ori", [True, False])
def test_order_history_accepts_both_quantity_spellings(env: Env, ori: bool) -> None:
    """D9: `oriQty` in history, `origQty` elsewhere."""
    env.mock.history_uses_ori_qty = ori
    order = _limit(env)
    env.mock.fill(order.order_id, "0.001")
    assert env.client.get_order_history("BTCIDR")[0].orig_qty == Decimal("0.001")


def test_history_windows_over_seven_days_are_refused_client_side(env: Env) -> None:
    with pytest.raises(ValueError):
        env.client.get_order_history("BTCIDR", start_ms=0, end_ms=8 * 86_400_000)
    with pytest.raises(ValueError):
        env.client.get_my_trades("BTCIDR", start_ms=0, end_ms=8 * 86_400_000)
    assert env.client.get_my_trades("BTCIDR", start_ms=0, end_ms=7 * 86_400_000) == []


# ------------------------------------------------------------------- throttle


def test_the_throttle_keeps_a_burst_under_the_exchange_limit() -> None:
    env = Env(headroom=0.5)
    for _ in range(200):
        env.client.get_last_prices()  # the mock answers 429 if the throttle lets too many through
    assert env.sleeps, "the throttle never had to wait"


def test_token_bucket_waits_when_empty_and_refills_with_time() -> None:
    now = [0.0]
    waits: list[float] = []

    def sleep(s: float) -> None:
        waits.append(s)
        now[0] += s

    bucket = TokenBucket(rate_per_s=2, burst=2, clock=lambda: now[0], sleep=sleep)
    assert bucket.acquire() == 0 and bucket.acquire() == 0
    assert bucket.acquire() == pytest.approx(0.5)
    now[0] += 10
    assert bucket.acquire() == 0


def test_throttle_headroom_must_be_chosen() -> None:
    with pytest.raises(TypeError):
        Throttle()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Throttle(0)


# ------------------------------------------------------------- symbols, format


@pytest.mark.parametrize("raw", ["BTCIDR", "btcidr", "btc_idr", "BTC-IDR"])
def test_the_three_symbol_spellings_are_one_pair(raw: str) -> None:
    assert canonical(raw) == "BTCIDR"


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("1E+3"), "1000"),
        (Decimal("0.00100"), "0.001"),
        (Decimal("0"), "0"),
        (Decimal("12345678.9"), "12345678.9"),
    ],
)
def test_decimals_are_formatted_without_exponent(value: Decimal, expected: str) -> None:
    assert fmt(value) == expected


# --------------------------------------------------------------------- guards


def test_the_public_surface_equals_the_allowlist() -> None:
    """ADR-013: no withdrawal, deposit, fiat, or generic-request method can be added silently."""
    public = {
        n
        for n in dir(IndodaxClient)
        if not n.startswith("_") and callable(getattr(IndodaxClient, n))
    }
    assert public == ALLOWED_METHODS
    assert not {
        n for n in public if any(w in n for w in ("withdraw", "deposit", "fiat", "request", "call"))
    }


def test_only_the_connector_orders_and_killswitch_may_use_the_write_methods() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "aidss_trader"
    allowed_dirs = {"connector", "orders", "killswitch"}
    offenders = []
    files = list(root.rglob("*.py"))
    assert len(files) > 10
    for path in files:
        if path.relative_to(root).parts[0] in allowed_dirs:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in {"create_order", "cancel_order"}:
                offenders.append(str(path.relative_to(root)))
    assert not offenders, f"write methods used outside connector/orders/killswitch: {offenders}"
