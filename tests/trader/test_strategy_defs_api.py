"""The strategy library API: kinds, definitions, delete guards, and the backtest job.

Test values only; nothing here touches an exchange.
"""

from __future__ import annotations

import time

from tests.trader.test_runtime_wiring import World, api_for

DONCHIAN = {
    "entry_period": "20",
    "exit_period": "10",
    "atr_period": "14",
    "atr_stop_multiple": "2.5",
    "cooldown_s": "14400",
}
EMA = {
    "ema_fast": "3",
    "ema_slow": "6",
    "adx_period": "3",
    "adx_threshold": "30",
    "atr_period": "3",
    "atr_stop_multiple": "2",
    "cooldown_s": "0",
}


def _create(call, sid="my_breakout", params=None, kind="donchian_breakout"):
    return call(
        "POST",
        "/strategy-defs",
        {"id": sid, "label": "My breakout", "kind": kind, "params": params or DONCHIAN},
    )


def test_kinds_list_every_rule_with_bounds_and_no_defaults() -> None:
    call = api_for(World("PAPER", configured=False))
    kinds = {k["kind"]: k for k in call("GET", "/strategy-kinds").json()["data"]}
    assert set(kinds) == {
        "ema_adx",
        "donchian_breakout",
        "rsi_reversion",
        "bollinger_reversion",
        "macd_trend",
    }
    assert {f["name"] for f in kinds["rsi_reversion"]["fields"]} >= {"rsi_period", "oversold"}


def test_create_edit_and_delete_a_strategy() -> None:
    call = api_for(World("PAPER", configured=False))
    made = _create(call)
    assert made.status_code == 201
    version = made.json()["data"]["version"]
    assert version.startswith("donchian_breakout-")
    listed = {d["id"]: d for d in call("GET", "/strategy-defs").json()["data"]}
    assert listed["my_breakout"]["version"] == version and listed["my_breakout"]["legacy"] is False

    edited = call(
        "PUT",
        "/strategy-defs/my_breakout",
        {"label": "Wider", "params": {**DONCHIAN, "entry_period": "30"}},
    )
    assert edited.status_code == 200 and edited.json()["data"]["version"] != version
    assert call("DELETE", "/strategy-defs/my_breakout").status_code == 200
    assert call("DELETE", "/strategy-defs/my_breakout").status_code == 404


def test_bad_definitions_are_refused_with_the_reason() -> None:
    call = api_for(World("PAPER", configured=False))
    assert _create(call, "Bad Id").json()["error"]["code"] == "bad_id"
    assert _create(call, "ema_adx").status_code == 409
    for bad in (
        {**DONCHIAN, "entry_period": "5", "exit_period": "9"},  # exit channel longer than entry
        {**DONCHIAN, "atr_stop_multiple": "0"},
        {**DONCHIAN, "entry_period": "400"},
        {k: v for k, v in DONCHIAN.items() if k != "cooldown_s"},  # no default numbers
        {**DONCHIAN, "extra": "1"},
    ):
        r = _create(call, "x_try", bad)
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_parameters", bad
    assert _create(call, "my_breakout").status_code == 201
    assert _create(call, "my_breakout").status_code == 409  # id already taken


def test_the_reference_strategy_is_edited_through_its_own_route() -> None:
    call = api_for(World("PAPER", configured=False))
    assert (
        call(
            "PUT",
            "/strategies/ema_adx/parameters",
            {
                "ema_fast": 3,
                "ema_slow": 6,
                "adx_period": 3,
                "adx_threshold": "30",
                "atr_period": 3,
                "atr_stop_multiple": "2",
                "cooldown_s": 0,
            },
        ).status_code
        == 200
    )
    ema = next(d for d in call("GET", "/strategy-defs").json()["data"] if d["id"] == "ema_adx")
    assert ema["legacy"] is True and ema["kind"] == "ema_adx" and ema["mode"] == "PAPER"
    r = call("PUT", "/strategy-defs/ema_adx", {"label": "x", "params": EMA})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_parameters_route"
    # Nothing is open, so the reference strategy may be removed like any other.
    assert call("DELETE", "/strategy-defs/ema_adx").status_code == 200


def test_a_backtest_without_the_owners_numbers_fails_with_a_reason() -> None:
    call = api_for(World("PAPER", configured=False))
    _create(call)
    started = call("POST", "/backtests", {"strategy_ids": ["my_breakout"]})
    assert started.status_code == 202
    job_id = started.json()["data"]["id"]
    for _ in range(100):
        job = call("GET", f"/backtests/{job_id}").json()["data"]
        if job["state"] != "RUNNING":
            break
        time.sleep(0.05)
    assert job["state"] == "FAILED" and job["error"]
    assert call("POST", "/backtests", {"strategy_ids": ["nope"]}).status_code == 404
    assert call("GET", "/backtests/missing").status_code == 404
