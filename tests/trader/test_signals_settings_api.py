"""The crypto signal worker's settings, history and screen API (ADR-066): validation, the one
default, step-up for anything that loosens, the explicit PUBLISH confirmation, run-now, and the
history reads. SQLite and the mock exchange only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from aidss_trader.db.models import SignalAckRow, SignalCandidate, SignalScan
from aidss_trader.signals_config import (
    DEFAULT_TOP_N,
    SignalSettings,
    SignalSettingsError,
    loosens,
    parse_settings,
    unset_fields,
)
from tests.trader.test_runtime_wiring import World, api_for

FULL = {
    "enabled": True,
    "mode": "SHADOW",
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "top_n": 5,
    "min_quote_volume_usdt": "50000000",
    "horizons": ["14d", "30d"],
    "min_score_ratio": "0.8",
    "atr_stop_multiple": "2.5",
    "tp_r": ["1.5", "2.5", "4"],
    "ai_min_score": 70,
    "ai_max_calls": 10,
}


def settings(**over) -> SignalSettings:
    return parse_settings({**FULL, **over})


# ------------------------------------------------------------------------- the settings


def test_the_only_default_is_the_owners_top_n() -> None:
    blank = parse_settings({})
    assert blank.top_n == DEFAULT_TOP_N == 5
    assert blank.enabled is False and blank.mode == "SHADOW"
    assert blank.min_score_ratio is None and blank.tp_r is None and blank.ai_min_score is None
    # top_n alone already gives the worker something to scan, so only the numbers are unset
    assert set(unset_fields(blank)) == {
        "min_quote_volume_usdt",
        "horizons",
        "min_score_ratio",
        "atr_stop_multiple",
        "tp_r",
        "ai_min_score",
        "ai_max_calls",
    }
    assert unset_fields(settings()) == []


def test_every_problem_is_reported_together() -> None:
    with pytest.raises(SignalSettingsError) as err:
        parse_settings(
            {
                "mode": "LIVE",
                "symbols": ["btc/usdt", "ETHUSDT", "ETHUSDT"],
                "top_n": 99,
                "horizons": ["3d"],
                "min_score_ratio": "1.5",
                "atr_stop_multiple": "-1",
                "tp_r": ["3", "2", "1"],
                "ai_min_score": 0,
                "ai_max_calls": 99,
                "min_quote_volume_usdt": "x",
            }
        )
    text = " | ".join(err.value.problems)
    for part in (
        "mode",
        "BTC/USDT",
        "duplicate",
        "top_n",
        "horizons",
        "min_score_ratio",
        "atr_stop_multiple",
        "tp_r",
        "ai_min_score",
        "ai_max_calls",
        "min_quote_volume",
    ):
        assert part in text, part


def test_top_n_zero_with_no_symbols_leaves_nothing_to_scan() -> None:
    s = settings(symbols=[], top_n=0)
    assert "symbols_or_top_n" in unset_fields(s)
    assert "symbols_or_top_n" not in unset_fields(settings(symbols=[], top_n=3))


def test_loosening_is_exactly_what_makes_the_worker_act_more_readily() -> None:
    base = settings()
    assert not loosens(base, base)
    for over in (
        {"mode": "PUBLISH"},
        {"min_score_ratio": "0.7"},
        {"ai_min_score": 60},
        {"min_quote_volume_usdt": "1000"},
        {"top_n": 6},
        {"atr_stop_multiple": "3"},
        {"ai_max_calls": 11},
    ):
        assert loosens(base, settings(**over)), over
    for over in (
        {"min_score_ratio": "0.9"},
        {"ai_min_score": 80},
        {"min_quote_volume_usdt": "9999999999"},
        {"top_n": 2},
        {"atr_stop_multiple": "2"},
        {"ai_max_calls": 3},
        {"enabled": False},
        {"symbols": ["BTCUSDT"]},
        {"horizons": ["30d"]},
        {"mode": "SHADOW"},
    ):
        assert not loosens(base, settings(**over)), over
    assert not loosens(SignalSettings(), settings())  # nothing was set before: nothing to loosen


# --------------------------------------------------------------------------------- the API


def put(call, body, **headers):
    return call("PUT", "/signals/config", body, **headers)


def grant(call) -> dict:
    g = call("POST", "/stepup", {"email": "o@x", "password": "pw", "scope": "RAISE_LIMIT"})
    return {"X-Step-Up": g.json()["data"]["grant"]}


def test_a_fresh_install_has_no_config_and_says_what_is_unset() -> None:
    call = api_for(World("PAPER", configured=False))
    data = call("GET", "/signals/config").json()["data"]
    assert data["configured"] is False and data["ready"] is False
    assert data["default_top_n"] == 5 and data["settings"]["top_n"] == 5
    assert "min_score_ratio" in data["unset"] and data["valid_horizons"] == [
        "1d",
        "7d",
        "14d",
        "30d",
    ]
    assert call("GET", "/signals/config").json()["meta"]["origin"] == "PAPER"


def test_saving_in_shadow_needs_no_password_and_is_audited() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    r = put(call, FULL)
    assert r.status_code == 200 and r.json()["data"]["ready"] is True
    got = call("GET", "/signals/config").json()["data"]
    assert got["settings"]["min_score_ratio"] == "0.8" and got["settings"]["tp_r"] == [
        "1.5",
        "2.5",
        "4",
    ]
    assert got["updated_by"]
    with w.factory() as s:
        from sqlalchemy import select

        from aidss_trader.db.models import AuditLog as Row

        assert s.scalar(select(Row).where(Row.action == "signal_config.change")) is not None


def test_a_bad_body_is_refused_with_every_reason() -> None:
    call = api_for(World("PAPER", configured=False))
    r = put(call, {**FULL, "min_score_ratio": "2", "horizons": ["3d"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_settings"
    assert (
        "min_score_ratio" in r.json()["error"]["message"]
        and "horizons" in r.json()["error"]["message"]
    )


def test_lowering_the_bar_or_adding_coins_needs_the_password() -> None:
    call = api_for(World("PAPER", configured=False))
    assert put(call, FULL).status_code == 200
    for over in ({"min_score_ratio": "0.7"}, {"top_n": 9}, {"ai_min_score": 50}):
        r = put(call, {**FULL, **over})
        assert r.status_code == 403 and r.json()["error"]["code"] == "step_up_required", over
    ok = put(call, {**FULL, "min_score_ratio": "0.7"}, **grant(call))
    assert ok.status_code == 200
    tighter = put(call, {**FULL, "min_score_ratio": "0.9"})  # raising it is free
    assert tighter.status_code == 200


def test_publish_needs_the_confirmation_the_password_and_a_complete_config() -> None:
    call = api_for(World("PAPER", configured=False))
    assert put(call, FULL).status_code == 200
    publish = {**FULL, "mode": "PUBLISH"}
    no_confirm = put(call, publish, **grant(call))
    assert (
        no_confirm.status_code == 400
        and no_confirm.json()["error"]["code"] == "confirm_publish_required"
    )
    no_password = put(call, {**publish, "confirm_publish": True})
    assert no_password.status_code == 403
    done = put(call, {**publish, "confirm_publish": True}, **grant(call))
    assert done.status_code == 200 and done.json()["data"]["settings"]["mode"] == "PUBLISH"
    # back to SHADOW needs nothing
    assert put(call, FULL).status_code == 200
    incomplete = {**FULL, "mode": "PUBLISH", "confirm_publish": True, "tp_r": None}
    r = put(call, incomplete, **grant(call))
    assert r.status_code == 400 and "tp_r" in r.json()["error"]["message"]


def test_scan_now_needs_a_ready_enabled_worker_and_marks_the_request() -> None:
    call = api_for(World("PAPER", configured=False))
    assert call("POST", "/signals/run").status_code == 409  # nothing configured
    put(call, {**FULL, "enabled": False})
    assert call("POST", "/signals/run").status_code == 409  # not enabled
    put(call, FULL)
    r = call("POST", "/signals/run")
    assert r.status_code == 202 and r.json()["data"]["run_requested_at"]
    status = call("GET", "/signals/status").json()["data"]
    assert status["run_pending"] is True and status["ready"] and status["enabled"]


def seed(w: World) -> None:
    now = datetime.now(UTC)
    with w.factory() as s:
        scan = SignalScan(
            id=uuid.uuid4(),
            kind="SCHEDULED",
            status="DONE",
            mode="SHADOW",
            started_at=now,
            finished_at=now,
            universe=["BTCUSDT", "ETHUSDT"],
            outcomes={"BTCUSDT": "SIGNAL", "ETHUSDT": "BELOW_THRESHOLD"},
            errors=[],
            ai_calls=1,
            signals=1,
        )
        s.add(scan)
        s.flush()
        for sym, ratio, meets, outcome in (
            ("BTCUSDT", "0.9", True, "SIGNAL"),
            ("ETHUSDT", "0.4", False, "BELOW_THRESHOLD"),
        ):
            s.add(
                SignalCandidate(
                    scan_id=scan.id,
                    symbol=sym,
                    day="2026-11-20",
                    scored_at=now,
                    mode="SHADOW",
                    eligible=True,
                    reason="ok",
                    score=D("7"),
                    max_score=D("7.8"),
                    score_ratio=D(ratio),
                    meets_threshold=meets,
                    outcome=outcome,
                    met={"14d": ["trend_has_strength"]},
                    not_met={"14d": ["not_stretched"]},
                    ai={"score": 85} if meets else None,
                    levels={"entry": 1.0, "stop": 0.9} if meets else None,
                    signal_id="aidss-BTCUSDT-2026-11-20" if meets else None,
                )
            )
        s.add(SignalAckRow(signal_id="aidss-BTCUSDT-2026-11-20", stage="RECEIVED", received_at=now))
        s.add(
            SignalAckRow(
                signal_id="aidss-BTCUSDT-2026-11-20",
                stage="RESULT",
                environment="LIVE",
                status="DISABLED",
                reason="auto-execute off",
                received_at=now + timedelta(seconds=1),
            )
        )
        s.commit()


def test_history_reads_filter_by_criteria_symbol_and_outcome() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    seed(w)
    everything = call("GET", "/signals/candidates").json()["data"]
    assert everything["total"] == 2
    met = call("GET", "/signals/candidates?meets=true").json()["data"]
    assert [x["symbol"] for x in met["items"]] == ["BTCUSDT"] and met["items"][0]["ai"][
        "score"
    ] == 85
    assert (
        float(met["items"][0]["score_ratio"]) == pytest.approx(0.9)
        and met["items"][0]["levels"]["entry"] == 1.0
    )
    assert (
        call("GET", "/signals/candidates?meets=false").json()["data"]["items"][0]["symbol"]
        == "ETHUSDT"
    )
    assert call("GET", "/signals/candidates?symbol=ethusdt").json()["data"]["total"] == 1
    assert call("GET", "/signals/candidates?outcome=signal").json()["data"]["total"] == 1
    page = call("GET", "/signals/candidates?limit=1&offset=1").json()["data"]
    assert page["total"] == 2 and len(page["items"]) == 1
    acks = call("GET", "/signals/acks").json()["data"]
    assert [a["stage"] for a in acks] == ["RESULT", "RECEIVED"] and acks[0]["status"] == "DISABLED"
    scans = call("GET", "/signals/scans").json()["data"]
    assert scans[0]["signals"] == 1 and scans[0]["outcomes"]["ETHUSDT"] == "BELOW_THRESHOLD"


def test_status_reports_the_last_scan_and_flags_a_silent_worker() -> None:
    w = World("PAPER", configured=False)
    call = api_for(w)
    put(call, FULL)
    never = call("GET", "/signals/status").json()["data"]
    assert never["last_scan"] is None and never["stale"] is True  # enabled and ready, never scanned
    seed(w)
    fresh = call("GET", "/signals/status").json()["data"]
    assert fresh["last_scan"]["mode"] == "SHADOW" and fresh["stale"] is False
    with w.factory() as s:
        for scan in s.query(SignalScan):
            scan.started_at = datetime.now(UTC) - timedelta(hours=40)
        s.commit()
    assert call("GET", "/signals/status").json()["data"]["stale"] is True
    put(call, {**FULL, "enabled": False})
    assert (
        call("GET", "/signals/status").json()["data"]["stale"] is False
    )  # off: silence is expected
