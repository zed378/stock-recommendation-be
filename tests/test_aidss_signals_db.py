"""The signal worker in database mode (ADR-066): when a pass is due, what it stores, and that the
owner's settings are what drive it. SQLite, synthetic candles, a scripted reviewer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_signals.ai_review import AiUnavailable, Verdict
from aidss_signals.config import config_from_settings
from aidss_signals.runner import due_pass, poll_once, schedule_slot
from aidss_signals.store import DbState, SignalStore
from aidss_trader.db.base import Base
from aidss_trader.db.models import SignalAckRow, SignalCandidate, SignalScan
from aidss_trader.signals_config import parse_settings, request_run, set_signal_settings
from tests.test_aidss_signals import NOW, candles, market, rows, tick

SETTINGS = {
    "enabled": True,
    "mode": "SHADOW",
    "symbols": ["ETHUSDT", "SOLUSDT"],
    "top_n": 0,
    "min_quote_volume_usdt": "1000000",
    "horizons": ["14d", "30d"],
    "min_score_ratio": "0.8",
    "atr_stop_multiple": "2",
    "tp_r": ["1.5", "2.5", "4"],
    "ai_min_score": 70,
    "ai_max_calls": 10,
}
GOOD = Verdict(82, "TAKE", "MEDIUM", ("trend and structure agree",), ("extended",))
ENV = {"AIDSS_SIGNALS_DATA_DIR": "x"}


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def configure(factory, **over):
    with factory() as s:
        set_signal_settings(s, parse_settings({**SETTINGS, **over}), by="owner", now=NOW)
        s.commit()


def universe():
    up, down = candles(260, 0.006, 1), candles(260, -0.006, 2)
    tickers = [tick("ETHUSDT", "5000000000"), tick("SOLUSDT", "4000000000")]
    return market({"BTCUSDT": rows(up), "ETHUSDT": rows(up), "SOLUSDT": rows(down)}, tickers)


def poll(store, factory, review=lambda d: GOOD, now=NOW, ready=False, published=None, logs=None):
    sent = published if published is not None else []
    lines = logs if logs is not None else []
    return poll_once(
        store,
        lambda cfg: universe(),
        lambda: review,
        sent.append,
        ENV,
        now,
        lambda lvl, msg: lines.append(msg),
        ready,
    )


# ------------------------------------------------------------------------------ schedule


def test_the_schedule_slot_is_the_latest_five_past_midnight_utc() -> None:
    assert schedule_slot(datetime(2026, 11, 21, 0, 4, tzinfo=UTC)) == datetime(
        2026, 11, 20, 0, 5, tzinfo=UTC
    )
    assert schedule_slot(datetime(2026, 11, 21, 0, 5, tzinfo=UTC)) == datetime(
        2026, 11, 21, 0, 5, tzinfo=UTC
    )
    assert schedule_slot(datetime(2026, 11, 21, 17, 0, tzinfo=UTC)) == datetime(
        2026, 11, 21, 0, 5, tzinfo=UTC
    )


def test_a_pass_is_due_once_per_slot_and_whenever_the_owner_asks(factory) -> None:
    store = SignalStore(factory, now=lambda: NOW)
    assert due_pass(store, NOW, None).kind == "SCHEDULED"  # never scanned
    sid = store.begin_scan("SCHEDULED", "SHADOW")
    store.finish_scan(
        sid, status="DONE", universe=[], outcomes={}, errors=[], ai_calls=0, signals=0
    )
    assert due_pass(store, NOW + timedelta(hours=3), None) is None  # same slot
    assert due_pass(store, NOW + timedelta(days=1), None).kind == "SCHEDULED"  # next day's slot
    asked = NOW + timedelta(hours=1)
    assert due_pass(store, NOW + timedelta(hours=2), asked).kind == "MANUAL"
    store2 = SignalStore(factory, now=lambda: asked + timedelta(minutes=1))
    store2.begin_scan("MANUAL", "SHADOW")
    assert due_pass(store2, NOW + timedelta(hours=2), asked) is None  # answered


# ----------------------------------------------------------------------------- the poll


def test_idle_without_settings_when_disabled_or_incomplete(factory) -> None:
    store = SignalStore(factory, now=lambda: NOW)
    logs: list[str] = []
    assert poll(store, factory, logs=logs) is None  # no row at all
    configure(factory, enabled=False)
    assert poll(store, factory, logs=logs) is None
    configure(factory, min_score_ratio=None, tp_r=None)
    assert poll(store, factory, logs=logs) is None
    assert any("not set" in m and "min_score_ratio" in m for m in logs)
    with factory() as s:
        assert s.scalars(select(SignalScan)).first() is None  # nothing ran, nothing recorded


def test_a_due_pass_stores_the_scan_and_every_scored_coin_with_whether_it_qualified(
    factory,
) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    report = poll(store, factory)
    assert report.outcomes == {"ETHUSDT": "SIGNAL", "SOLUSDT": "BELOW_THRESHOLD"}
    with factory() as s:
        scan = s.scalars(select(SignalScan)).one()
        assert (scan.kind, scan.status, scan.mode, scan.signals, scan.ai_calls) == (
            "SCHEDULED",
            "DONE",
            "SHADOW",
            1,
            1,
        )
        assert scan.outcomes["SOLUSDT"] == "BELOW_THRESHOLD" and sorted(scan.universe) == [
            "ETHUSDT",
            "SOLUSDT",
        ]
        rows_ = {c.symbol: c for c in s.scalars(select(SignalCandidate))}
        eth, sol = rows_["ETHUSDT"], rows_["SOLUSDT"]
        assert eth.meets_threshold is True and eth.outcome == "SIGNAL" and eth.mode == "SHADOW"
        assert float(eth.score_ratio) > 0.8 and eth.ai["score"] == 82 and eth.levels["entry"] > 0
        assert eth.signal_id == "aidss-ETHUSDT-" + eth.day and "14d" in eth.met and eth.eligible
        assert sol.meets_threshold is False and sol.outcome == "BELOW_THRESHOLD" and sol.ai is None
        assert float(sol.score_ratio) < 0.8 and sol.met and sol.not_met


def test_the_same_slot_is_not_scanned_twice_but_a_request_from_the_screen_is(factory) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    assert poll(store, factory) is not None
    assert poll(store, factory, now=NOW + timedelta(hours=1)) is None
    later = NOW + timedelta(hours=2)
    with factory() as s:
        request_run(s, by="owner", now=NOW + timedelta(hours=1, minutes=30))
        s.commit()
    store = SignalStore(factory, now=lambda: later)
    report = poll(store, factory, now=later)
    assert report is not None
    with factory() as s:
        kinds = [x.kind for x in s.scalars(select(SignalScan).order_by(SignalScan.started_at))]
        assert kinds == ["SCHEDULED", "MANUAL"]
        assert len(s.scalars(select(SignalCandidate)).all()) == 4  # scored again, history kept


def test_changing_a_setting_on_the_screen_changes_the_next_pass(factory) -> None:
    configure(factory, min_score_ratio="0.99")
    store = SignalStore(factory, now=lambda: NOW)
    first = poll(store, factory)
    assert first.outcomes["ETHUSDT"] == "BELOW_THRESHOLD"  # a stricter bar, set by the owner
    configure(factory, min_score_ratio="0.5")
    with factory() as s:
        request_run(s, by="owner", now=NOW + timedelta(minutes=1))
        s.commit()
    later = NOW + timedelta(minutes=2)
    second = poll(SignalStore(factory, now=lambda: later), factory, now=later)
    assert second.outcomes["ETHUSDT"] == "SIGNAL"


def test_publish_without_a_receiver_runs_as_shadow_and_says_so(factory) -> None:
    configure(factory, mode="PUBLISH")
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []
    logs: list[str] = []
    report = poll(store, factory, published=sent, logs=logs, ready=False)
    assert sent == [] and report.outcomes["ETHUSDT"] == "SIGNAL"
    assert any("no receiver" in m for m in logs)
    with factory() as s:
        assert s.scalars(select(SignalScan)).one().mode == "SHADOW"
        assert {c.mode for c in s.scalars(select(SignalCandidate))} == {"SHADOW"}


def test_publish_with_a_receiver_sends_once_per_day_even_across_scans(factory) -> None:
    configure(factory, mode="PUBLISH")
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []
    poll(store, factory, published=sent, ready=True)
    assert [s["id"] for s in sent][0].startswith("aidss-ETHUSDT-") and len(sent) == 1
    with factory() as s:
        request_run(s, by="owner", now=NOW + timedelta(minutes=1))
        s.commit()
    later = NOW + timedelta(minutes=2)
    again = poll(
        SignalStore(factory, now=lambda: later), factory, now=later, published=sent, ready=True
    )
    assert len(sent) == 1 and again.outcomes["ETHUSDT"] == "ALREADY_DECIDED"


def test_a_shadow_signal_does_not_block_a_later_real_one(factory) -> None:
    configure(factory)  # SHADOW
    store = SignalStore(factory, now=lambda: NOW)
    poll(store, factory)
    assert DbState(store).decided("ETHUSDT", "2026-11-20") is False


def test_an_unavailable_review_is_recorded_and_publishes_nothing(factory) -> None:
    configure(factory, mode="PUBLISH")
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []

    def down(d):
        raise AiUnavailable("provider unreachable")

    report = poll(store, factory, review=down, published=sent, ready=True)
    assert sent == [] and report.outcomes["ETHUSDT"] == "AI_UNAVAILABLE"
    with factory() as s:
        eth = s.scalars(select(SignalCandidate).where(SignalCandidate.symbol == "ETHUSDT")).one()
        assert eth.outcome == "AI_UNAVAILABLE" and eth.meets_threshold is True and eth.ai is None


def test_a_pass_that_breaks_leaves_a_failed_scan_not_a_silent_gap(factory) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)

    def explode(cfg):
        raise RuntimeError("boom")

    assert poll_once(store, explode, lambda: GOOD, lambda s: None, ENV, NOW) is None
    with factory() as s:
        scan = s.scalars(select(SignalScan)).one()
        assert scan.status == "FAILED" and scan.errors == ["RuntimeError"]


def test_acknowledgements_are_kept(factory) -> None:
    store = SignalStore(factory, now=lambda: NOW)
    store.save_ack({"signalId": "aidss-ETHUSDT-2026-11-20", "stage": "RECEIVED"})
    store.save_ack(
        {
            "signalId": "aidss-ETHUSDT-2026-11-20",
            "stage": "RESULT",
            "environment": "LIVE",
            "status": "DISABLED",
            "reason": "auto-execute off",
        }
    )
    with factory() as s:
        acks = s.scalars(select(SignalAckRow).order_by(SignalAckRow.stage.desc())).all()
        assert [(a.stage, a.environment, a.status) for a in acks] == [
            ("RESULT", "LIVE", "DISABLED"),
            ("RECEIVED", None, None),
        ]


def test_config_from_settings_keeps_the_secret_in_the_environment() -> None:
    s = parse_settings(SETTINGS)
    cfg = config_from_settings(
        s, {"AIDSS_SIGNALS_CLIENT_TOKEN": "tok-" + "x" * 20, "AIDSS_SIGNALS_PORT": "3099"}
    )
    assert cfg.mode == "SHADOW" and cfg.min_score_ratio == 0.8 and cfg.tp_r == (1.5, 2.5, 4.0)
    assert (
        cfg.port == 3099 and "tok-" not in repr(cfg) and cfg.fixed_symbols == ("ETHUSDT", "SOLUSDT")
    )
