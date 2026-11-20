"""Indodax builder: synthetic exchange and model doubles, no network inference."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from aidss_trader.audit import verify_chain
from aidss_trader.db.models import AuditLog, BuilderReview, Candle, OrderIntentRow, StrategyRow
from aidss_trader.runtime.builder_reviews import build_work, entry_review
from aidss_trader.strategy.base import PositionState, SignalKind
from aidss_trader.strategy.kinds import ParameterError, build_strategy
from tests.trader.test_runtime_wiring import USERS, World, api_for, warm


def definition():
    rule = {
        "name": "positive close",
        "left": {"indicator": "close"},
        "operator": "gt",
        "right": {"indicator": "constant", "value": "0"},
    }
    return {
        "exchange": "INDODAX",
        "quote": "IDR",
        "timeframe": "4H",
        "entry": {"mode": "ALL", "rules": [rule]},
        "exit": {"mode": "ANY", "rules": [rule]},
        "atr_period": 3,
        "atr_stop_multiple": "2",
        "cooldown_s": 0,
        "max_data_age_seconds": 3600,
        "max_review_age_seconds": 600,
        "forecast_bars": 1,
        "forecast_samples": 1,
        "min_projected_return_pct": "0",
        "ai_min_score": 70,
    }


@pytest.fixture
def world(monkeypatch):
    w = World("PAPER")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return w.now()

    call = api_for(w)
    monkeypatch.setattr("aidss_trader.api.app.datetime", Clock)
    with w.factory() as s:
        # Isolate the builder from the separate reference strategy's pair claim.
        s.get(StrategyRow, "ema_adx").version = "not-this-test"
        s.commit()
    made = call(
        "POST",
        "/strategy-defs",
        {
            "id": "aa_builder",
            "label": "Test only",
            "kind": "signal_builder",
            "params": {"definition": json.dumps(definition())},
        },
    )
    assert made.status_code == 201, made.text
    assert call("PUT", "/strategy-defs/aa_builder/paper", {"enabled": True}).status_code == 200
    warm(w)
    return w, call


def work(call):
    response = call("GET", "/signal-builder/work")
    assert response.status_code == 200, response.text
    jobs = response.json()["data"]
    assert len(jobs) == 1
    return jobs[0]


def review(job):
    return {
        "identity": job["identity"],
        "strategy_id": "aa_builder",
        "pair": "BTCIDR",
        "kronos": {
            "provider": "huggingface",
            "model_id": "synthetic-double",
            "ticker": "BTCIDR",
            "exchange": "INDODAX",
            "timeframe": "4h",
            "as_of": job["candle_open"],
            "pred_len": 1,
            "samples": 1,
            "projected_return_pct": "1",
        },
        "ai": {"score": 80, "verdict": "TAKE", "confidence": "MEDIUM", "reasons": [], "risks": []},
    }


def test_paper_entry_requires_review_and_records_its_id(world):
    w, call = world
    assert not w.rows(OrderIntentRow) and w.posts() == 0
    assert any("review_pending" in why for why in w.cycle().skipped)
    body = review(work(call))
    response = call("POST", "/signal-builder/reviews", body)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["outcome"] == "PASS"
    w.cycle()
    intents = w.rows(OrderIntentRow)
    assert len(intents) == 1 and intents[0].origin == "PAPER" and w.posts() == 0
    assert intents[0].rule_snapshot["builder_review_id"] == response.json()["data"]["id"]
    assert intents[0].stop_price > 0


@pytest.mark.parametrize(
    "stage,change",
    [
        ("kronos", {"provider": "fixture"}),
        ("kronos", {"ticker": "BTCUSDT"}),
        ("kronos", {"projected_return_pct": "-1"}),
        ("kronos", {"samples": 2}),
        ("ai", {"verdict": "SKIP"}),
        ("ai", {"score": 69}),
    ],
)
def test_model_veto_and_source_mismatch_block_paper_entry(world, stage, change):
    w, call = world
    body = review(work(call))
    body[stage].update(change)
    response = call("POST", "/signal-builder/reviews", body)
    assert response.status_code == 200 and response.json()["data"]["outcome"] == "BLOCKED"
    w.cycle()
    assert not w.rows(OrderIntentRow) and w.posts() == 0


def test_review_is_append_only_idempotent_and_audited(world):
    w, call = world
    body = review(work(call))
    assert call("POST", "/signal-builder/reviews", body).status_code == 200
    assert call("POST", "/signal-builder/reviews", body).status_code == 200
    body["ai"]["score"] = 99
    assert call("POST", "/signal-builder/reviews", body).status_code == 409
    assert len(w.rows(BuilderReview)) == 1
    with w.factory() as s:
        assert verify_chain(s) > 0
        assert (
            len(
                s.scalars(
                    select(AuditLog).where(AuditLog.action == "builder_review_recorded")
                ).all()
            )
            == 1
        )


def test_changed_candles_or_settings_cannot_reuse_review(world):
    w, call = world
    job = work(call)
    body = review(job)
    assert call("POST", "/signal-builder/reviews", body).status_code == 200
    with w.factory() as s:
        row = s.scalar(select(Candle).order_by(Candle.open_time.desc()).limit(1))
        row.volume += Decimal("1")
        s.commit()
        new = build_work(s, "aa_builder", "BTCIDR", w.now())
        assert new["identity"] != job["identity"]
        strategy = build_strategy("signal_builder", {"definition": json.dumps(definition())})
        why, _ = entry_review(
            s, strategy, "aa_builder", "BTCIDR", "4H", w.runtime._load_candles(s, "BTCIDR"), w.now()
        )
        assert why == "builder_review_pending"
    updated = definition()
    updated["ai_min_score"] = 90
    assert (
        call(
            "PUT",
            "/strategy-defs/aa_builder",
            {"label": "Changed", "params": {"definition": json.dumps(updated)}},
        ).status_code
        == 200
    )
    assert work(call)["identity"] != job["identity"]


def test_expired_review_and_non_indodax_candles_block(world):
    w, call = world
    assert call("POST", "/signal-builder/reviews", review(work(call))).status_code == 200
    strategy = build_strategy("signal_builder", {"definition": json.dumps(definition())})
    with w.factory() as s:
        candles = w.runtime._load_candles(s, "BTCIDR")
        why, _ = entry_review(
            s, strategy, "aa_builder", "BTCIDR", "4H", candles, w.now() + timedelta(seconds=601)
        )
        assert why == "builder_review_stale"
        s.scalar(select(Candle).order_by(Candle.open_time.desc()).limit(1)).source = "binance"
        s.commit()
        assert build_work(s, "aa_builder", "BTCIDR", w.now()) is None


def test_exit_is_pure_and_does_not_need_a_review(world):
    w, _ = world
    strategy = build_strategy("signal_builder", {"definition": json.dumps(definition())})
    with w.factory() as s:
        candles = w.runtime._load_candles(s, "BTCIDR")
    assert strategy.evaluate(candles, PositionState(long=True)).kind == SignalKind.EXIT
    assert not w.rows(BuilderReview)


def test_review_routes_refuse_viewer_writes_and_missing_idempotency(world, monkeypatch):
    _, call = world
    body = review(work(call))
    monkeypatch.setitem(USERS, "viewer_test", ("u2", "viewer"))
    assert (
        call("GET", "/signal-builder/work", Authorization="Bearer viewer_test").status_code == 200
    )
    assert (
        call(
            "POST", "/signal-builder/reviews", body, Authorization="Bearer viewer_test"
        ).status_code
        == 403
    )
    assert (
        call("POST", "/signal-builder/reviews", body, **{"Idempotency-Key": ""}).status_code == 400
    )


def test_builder_definition_refuses_other_exchange_and_unset_stop():
    for change in ({"exchange": "BINANCE"}, {"quote": "USDT"}, {"atr_stop_multiple": None}):
        with pytest.raises(ParameterError):
            build_strategy("signal_builder", {"definition": json.dumps({**definition(), **change})})


def test_worker_end_to_end_records_once_without_exchange_operations(world):
    import httpx

    from aidss_signals.ai_review import Verdict
    from aidss_signals.indodax_builder import run_once

    w, call = world
    model_calls = []

    def forecast(cfg, bars):
        model_calls.append(cfg.symbol)
        close = bars[-1].close
        return {
            "provider": "huggingface",
            "model_id": "synthetic-double",
            "ticker": cfg.symbol,
            "exchange": "INDODAX",
            "timeframe": "4h",
            "pred_len": 1,
            "samples": 1,
            "as_of": bars[-1].timestamp.isoformat(),
            "last_close": str(close),
            "projected_return_pct": "1",
            "bars": [
                {
                    "timestamp": (bars[-1].timestamp + timedelta(hours=4)).isoformat(),
                    "open": str(close),
                    "close": str(close * Decimal("1.01")),
                    "high": str(close * Decimal("1.02")),
                    "low": str(close * Decimal("0.99")),
                    "volume": "1",
                }
            ],
        }

    def transport(request):
        path = request.url.path.removeprefix("/trader/v1")
        body = json.loads(request.content) if request.content else None
        response = call(request.method, path, body)
        return httpx.Response(response.status_code, json=response.json())

    with httpx.Client(
        base_url="https://internal.test", transport=httpx.MockTransport(transport)
    ) as client:
        def reviewer(_):
            return Verdict(80, "TAKE", "MEDIUM", (), ())
        assert run_once(client, forecast, reviewer, w.now()) == 1
        assert run_once(client, forecast, reviewer, w.now()) == 0
    assert model_calls == ["BTCIDR"] and w.posts() == 0
    assert len(w.rows(BuilderReview)) == 1
    w.cycle()
    assert len(w.rows(OrderIntentRow)) == 1 and w.posts() == 0


def test_passing_models_cannot_override_unset_risk_limits(world):
    from aidss_trader.config import RiskLimits, save_risk_limits

    w, call = world
    assert call("POST", "/signal-builder/reviews", review(work(call))).status_code == 200
    with w.factory() as s:
        save_risk_limits(s, RiskLimits(), set_by="test-owner")
        s.commit()
    w.cycle()
    assert not w.rows(OrderIntentRow) and w.posts() == 0
