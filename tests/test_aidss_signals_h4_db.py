"""The 4-hour breakout pass in database mode: when it is due, what it stores and publishes, that a
rescan cannot duplicate a signal, and that unfinished signals are followed to a simulated outcome
(ADR-067). SQLite and synthetic candles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_signals.h4_pass import btc_trend_4h, h4_slot, signal_payload
from aidss_signals.market import MarketData
from aidss_signals.runner import due_h4, poll_h4
from aidss_signals.store import SignalStore
from aidss_trader.db.base import Base
from aidss_trader.db.models import SignalScan, SignalTrade
from aidss_trader.signals_config import (
    parse_settings,
    request_run,
    set_signal_settings,
    unset_fields,
)

NOW = datetime(2026, 11, 21, 0, 10, tzinfo=UTC)  # ten minutes after the 00:00 UTC 4H close
H4_SETTINGS = {
    "enabled": True,
    "strategies": ["DONCHIAN", "SPIKE"],
    "donchian_n": 20,
    "vol_period": 20,
    "vol_mult": "2",
    "range_mult": "1.5",
    "min_score": 50,
    "allow_short": False,
    "max_hold_bars": 30,
    "fee_pct": "0.1",
    "slippage_pct": "0.05",
    "drift_r": "0.5",
}
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
    "h4": H4_SETTINGS,
}
ENV = {"AIDSS_SIGNALS_DATA_DIR": "x"}


def bar(open_time: datetime, o: float, high: float, low: float, c: float, v: float) -> list[object]:
    ms = int(open_time.timestamp() * 1000)
    return [ms, str(o), str(high), str(low), str(c), str(v), ms + 4 * 3600_000 - 1]


def last_open(now: datetime) -> datetime:
    return now.replace(hour=now.hour - now.hour % 4, minute=0, second=0, microsecond=0)


def quiet(
    now: datetime, n: int = 260, price: float = 100.0, drift: float = 0.0
) -> list[list[object]]:
    """n closed 4H bars ending with the candle that closed at or before `now`."""
    end = last_open(now) - timedelta(hours=4)
    rows = []
    for i in range(n):
        t = end - timedelta(hours=4 * (n - 1 - i))
        p = price * (1 + drift) ** i
        rows.append(bar(t, p, p + 1, p - 1, p + (0.2 if i % 2 else -0.2), 100.0))
    return rows


def breakout(rows: list[list[object]]) -> list[list[object]]:
    """Replace the last bar by a strong Donchian breakout on heavy volume."""
    t = datetime.fromtimestamp(int(rows[-1][0]) / 1000, UTC)
    base = float(rows[-2][4])
    return [*rows[:-1], bar(t, base, base + 4.5, base - 0.5, base + 4.3, 400.0)]


def mock(per_symbol: dict[str, object], tickers=None) -> MarketData:
    tickers = tickers or [
        {"symbol": s, "quoteVolume": "5000000000"} for s in per_symbol if s != "BTCUSDT"
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/ticker/24hr":
            return httpx.Response(200, json=tickers)
        assert request.url.params["interval"] == "4h"
        body = per_symbol[request.url.params["symbol"]]
        return httpx.Response(500) if isinstance(body, int) else httpx.Response(200, json=body)

    return MarketData(
        "https://x", httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def configure(factory, **over):
    body = {**SETTINGS, **over}
    with factory() as s:
        set_signal_settings(s, parse_settings(body), by="owner", now=NOW)
        s.commit()


def world(now: datetime = NOW):
    return {
        "BTCUSDT": quiet(now, drift=0.002),  # a rising BTC: bullish on 4H
        "ETHUSDT": breakout(quiet(now)),
        "SOLUSDT": quiet(now),
    }


def run(store, per_symbol, now=NOW, published=None, ready=False, logs=None):
    sent = published if published is not None else []
    lines = logs if logs is not None else []
    return poll_h4(
        store,
        lambda cfg: mock(per_symbol),
        sent.append,
        ENV,
        now,
        lambda lvl, msg: lines.append(msg),
        ready,
    )


# ----------------------------------------------------------------------------- schedule


def test_the_4h_slot_is_five_past_the_latest_4h_close_utc() -> None:
    assert h4_slot(datetime(2026, 11, 21, 0, 4, tzinfo=UTC)) == datetime(
        2026, 11, 20, 20, 5, tzinfo=UTC
    )
    assert h4_slot(datetime(2026, 11, 21, 0, 5, tzinfo=UTC)) == datetime(
        2026, 11, 21, 0, 5, tzinfo=UTC
    )
    assert h4_slot(datetime(2026, 11, 21, 13, 59, tzinfo=UTC)) == datetime(
        2026, 11, 21, 12, 5, tzinfo=UTC
    )


def test_a_4h_pass_is_due_once_per_slot_and_on_request(factory) -> None:
    store = SignalStore(factory, now=lambda: NOW)
    assert due_h4(store, NOW, None).kind == "H4"
    sid = store.begin_scan("H4", "SHADOW")
    store.finish_scan(
        sid, status="DONE", universe=[], outcomes={}, errors=[], ai_calls=0, signals=0
    )
    assert due_h4(store, NOW + timedelta(hours=2), None) is None
    assert due_h4(store, NOW + timedelta(hours=4), None).kind == "H4"
    asked = NOW + timedelta(hours=1)
    assert due_h4(store, NOW + timedelta(hours=2), asked).kind == "H4MANUAL"


def test_the_btc_4h_trend_is_bullish_bearish_choppy_or_unknown() -> None:
    def cs(drift):
        from aidss.domain.types import Candle

        return [
            Candle(
                datetime.fromtimestamp(int(r[0]) / 1000, UTC),
                D(str(r[1])),
                D(str(r[2])),
                D(str(r[3])),
                D(str(r[4])),
                D(str(r[5])),
            )
            for r in quiet(NOW, drift=drift)
        ]

    assert btc_trend_4h(cs(0.002)) == "bullish"
    assert btc_trend_4h(cs(-0.002)) == "bearish"
    assert btc_trend_4h(cs(0.0)) == "choppy"
    assert btc_trend_4h(cs(0.002)[:50]) == ""


# ------------------------------------------------------------------------------ the pass


def test_idle_unless_the_owner_switched_the_4h_signals_on_with_every_number(factory) -> None:
    store = SignalStore(factory, now=lambda: NOW)
    logs: list[str] = []
    assert run(store, world(), logs=logs) is None  # no settings
    configure(factory, h4={**H4_SETTINGS, "enabled": False})
    assert run(store, world(), logs=logs) is None
    configure(factory, h4={**H4_SETTINGS, "min_score": None, "drift_r": None})
    assert run(store, world(), logs=logs) is None
    assert any("h4.min_score" in m for m in logs)
    with factory() as s:
        assert s.scalars(select(SignalScan)).first() is None
    assert "h4.drift_r" in unset_fields(
        parse_settings({**SETTINGS, "h4": {**H4_SETTINGS, "drift_r": None}})
    )


def test_a_breakout_becomes_one_stored_signal_with_a_deterministic_id_in_shadow(factory) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []
    report = run(store, world(), published=sent)
    assert report.outcomes["SOLUSDT"] == "NO_SETUP" and report.outcomes["ETHUSDT"].startswith(
        "SIGNAL:"
    )
    assert sent == [] and len(report.new_signals) == 1
    with factory() as s:
        trade = s.scalars(select(SignalTrade)).one()
        scan = s.scalars(select(SignalScan)).one()
        assert scan.kind == "H4" and scan.mode == "SHADOW" and scan.signals == 1
        assert trade.signal_id.startswith("aidss4h-") and trade.symbol == "ETHUSDT"
        assert (trade.side, trade.mode, trade.published, trade.state) == (
            "LONG",
            "SHADOW",
            False,
            "PENDING",
        )
        assert (
            trade.btc_bias == "bullish"
            and 0 < trade.score <= 100
            and trade.components["btc"] == 20.0
        )
        assert (
            float(trade.stop)
            < float(trade.entry)
            < float(trade.tp1)
            < float(trade.tp2)
            < float(trade.tp3)
        )
        assert trade.candle_open.replace(tzinfo=UTC) == last_open(NOW) - timedelta(hours=4)


def test_a_rescan_or_a_manual_request_cannot_store_a_second_copy(factory) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    run(store, world())
    with factory() as s:
        request_run(s, by="owner", now=NOW + timedelta(minutes=1))
        s.commit()
    later = NOW + timedelta(minutes=2)
    again = poll_h4(
        SignalStore(factory, now=lambda: later),
        lambda cfg: mock(world()),
        lambda s: None,
        ENV,
        later,
        lambda lvl, msg: None,
        False,
    )
    assert again.outcomes["ETHUSDT"] == "ALREADY_SEEN" and again.new_signals == []
    with factory() as s:
        assert len(s.scalars(select(SignalTrade)).all()) == 1
        assert sorted(x.kind for x in s.scalars(select(SignalScan))) == ["H4", "H4MANUAL"]


def test_publish_with_a_receiver_sends_the_client_payload_and_marks_it_published(factory) -> None:
    configure(factory, mode="PUBLISH")
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []
    run(store, world(), published=sent, ready=True)
    assert len(sent) == 1
    p = sent[0]
    assert p["strategy"] in ("aidss_donchian_4h", "aidss_spike_4h") and p["side"] == "LONG"
    assert (
        p["id"].startswith("aidss4h-")
        and p["btcTrendBias"] == "bullish"
        and p["strength"] in ("HIGH", "MEDIUM", "LOW")
    )
    assert p["sl"] < p["entryPrice"] < p["tp1"] and isinstance(p["score"], int)
    assert p["analytics"]["timeframe"] == "4h" and "not a probability" in p["analytics"]["note"]
    with factory() as s:
        assert s.scalars(select(SignalTrade)).one().published is True


def test_publish_without_a_receiver_runs_as_shadow_and_publishes_nothing(factory) -> None:
    configure(factory, mode="PUBLISH")
    store = SignalStore(factory, now=lambda: NOW)
    sent: list[dict] = []
    logs: list[str] = []
    run(store, world(), published=sent, ready=False, logs=logs)
    assert sent == [] and any("no receiver" in m for m in logs)
    with factory() as s:
        assert s.scalars(select(SignalTrade)).one().mode == "SHADOW"


def test_the_minimum_score_and_the_short_switch_filter_what_is_stored(factory) -> None:
    configure(factory, h4={**H4_SETTINGS, "min_score": 80})
    store = SignalStore(factory, now=lambda: NOW)
    weak = quiet(NOW)
    t0 = datetime.fromtimestamp(int(weak[-1][0]) / 1000, UTC)
    base = float(weak[-2][4])
    weak[-1] = bar(t0, base, base + 1.8, base - 0.5, base + 1.6, 250.0)
    report = run(store, {**world(), "ETHUSDT": weak})
    assert report.outcomes["ETHUSDT"].startswith("BELOW_MIN_SCORE") and report.new_signals == []
    down = {
        "BTCUSDT": quiet(NOW, drift=-0.002),
        "ETHUSDT": breakout_down(quiet(NOW)),
        "SOLUSDT": quiet(NOW),
    }
    configure(factory, h4={**H4_SETTINGS, "allow_short": False})
    assert (
        run(SignalStore(factory, now=lambda: NOW), down, now=NOW + timedelta(hours=4)).new_signals
        == []
    )


def breakout_down(rows):
    t = datetime.fromtimestamp(int(rows[-1][0]) / 1000, UTC)
    base = float(rows[-2][4])
    return [*rows[:-1], bar(t, base, base + 0.5, base - 4.5, base - 4.3, 400.0)]


def test_btc_failure_stops_the_pass_and_one_bad_coin_does_not(factory) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    no_btc = {**world(), "BTCUSDT": 500}
    report = run(store, no_btc)
    assert report.new_signals == [] and report.errors
    with factory() as s:
        assert s.scalars(select(SignalTrade)).first() is None
    bad_coin = {**world(), "SOLUSDT": 500}
    later = NOW + timedelta(hours=4)
    configure(factory)
    report = run(
        SignalStore(factory, now=lambda: later), {**world(later), "SOLUSDT": 500}, now=later
    )
    assert report.outcomes["SOLUSDT"] == "DATA_ERROR" and report.outcomes["ETHUSDT"].startswith(
        "SIGNAL"
    )
    assert bad_coin is not None


# -------------------------------------------------------------------------------- tracking


def extend(rows: list[list[object]], *new: tuple[float, float, float, float]) -> list[list[object]]:
    t = datetime.fromtimestamp(int(rows[-1][0]) / 1000, UTC)
    out = list(rows)
    for i, (o, h, low, c) in enumerate(new, start=1):
        out.append(bar(t + timedelta(hours=4 * i), o, h, low, c, 100.0))
    return out


def test_an_unfinished_signal_is_followed_to_a_simulated_outcome_and_then_left_alone(
    factory,
) -> None:
    configure(factory)
    store = SignalStore(factory, now=lambda: NOW)
    first = world()
    run(store, first)
    with factory() as s:
        t = s.scalars(select(SignalTrade)).one()
        sid, entry, stop, tp1 = t.signal_id, float(t.entry), float(t.stop), float(t.tp1)
    assert t.state == "PENDING"
    # next candle: opens near the entry and runs through the stop at once
    after = extend(first["ETHUSDT"], (entry + 0.1, entry + 0.3, stop - 1.0, stop - 0.5))
    later = NOW + timedelta(hours=4)
    world2 = {**world(later), "ETHUSDT": after}
    report = run(SignalStore(factory, now=lambda: later), world2, now=later)
    assert report.tracked == 1 and report.closed == 1
    with factory() as s:
        t = s.scalars(select(SignalTrade).where(SignalTrade.signal_id == sid)).one()
        assert (t.state, t.outcome, t.tp_hits) == ("CLOSED", "SL", 0)
        assert (
            float(t.net_r) < float(t.gross_r) < 0 and t.bars_held == 1 and t.closed_at is not None
        )
        done_at, net = t.closed_at, t.net_r
    # a closed signal is never touched again, whatever the market does afterwards
    wilder = extend(after, (stop, tp1 + 20, stop - 5, tp1 + 15))
    much_later = later + timedelta(hours=4)
    run(
        SignalStore(factory, now=lambda: much_later),
        {**world(much_later), "ETHUSDT": wilder},
        now=much_later,
    )
    with factory() as s:
        t = s.scalars(select(SignalTrade).where(SignalTrade.signal_id == sid)).one()
        assert (t.closed_at, t.net_r, t.outcome) == (done_at, net, "SL")


def test_a_signal_whose_next_open_has_run_away_is_skipped_not_counted_as_a_trade(factory) -> None:
    configure(factory)
    first = world()
    run(SignalStore(factory, now=lambda: NOW), first)
    with factory() as s:
        first_trade = s.scalars(select(SignalTrade)).one()
        sid, entry = first_trade.signal_id, float(first_trade.entry)
    gapped = extend(first["ETHUSDT"], (entry + 30, entry + 31, entry + 29, entry + 30))
    later = NOW + timedelta(hours=4)
    run(SignalStore(factory, now=lambda: later), {**world(later), "ETHUSDT": gapped}, now=later)
    with factory() as s:
        t = s.scalars(select(SignalTrade).where(SignalTrade.signal_id == sid)).one()
        assert (t.state, t.outcome, t.net_r) == ("SKIPPED", "SKIPPED_DRIFT", None)


def test_the_payload_builder_uses_the_clients_field_names() -> None:
    from aidss_signals import h4

    setup = h4.Setup(h4.DONCHIAN, "SHORT", NOW, 100.0, 2.0, 83, {"btc": 20.0}, 99.0)
    lv = h4.levels("SHORT", 100.0, 2.0, 2.5, (1.5, 2.5, 4.0))
    p = signal_payload(setup, "ETHUSDT", "id-1", lv, "bearish")
    assert {
        "id",
        "symbol",
        "side",
        "entryPrice",
        "sl",
        "tp1",
        "tp2",
        "tp3",
        "strategy",
        "score",
        "strength",
        "btcTrendBias",
        "analytics",
    } <= set(p)
    assert p["sl"] > p["entryPrice"] > p["tp1"] and p["strength"] == "HIGH"


def test_the_atlas_strategy_says_why_a_small_universe_gives_no_shortlist(factory) -> None:
    # Percentile gates need many coins; two coins must not be treated as a universe.
    configure(factory, h4={**H4_SETTINGS, "strategies": ["ATLAS"]})
    store = SignalStore(factory, now=lambda: NOW)
    logs: list[str] = []
    report = run(store, world(), logs=logs)
    assert report.new_signals == []
    assert report.outcomes["ETHUSDT"].startswith("NO_SETUP:UNIVERSE_TOO_SMALL")
    assert any("atlas shortlist empty" in m and "UNIVERSE_TOO_SMALL" in m for m in logs)
    with factory() as s:
        assert s.scalars(select(SignalTrade)).first() is None


def test_a_coin_whose_candles_fail_is_reported_and_the_others_still_run(factory) -> None:
    configure(factory, h4={**H4_SETTINGS, "strategies": ["DONCHIAN", "ATLAS"]})
    store = SignalStore(factory, now=lambda: NOW)
    report = run(store, {**world(), "SOLUSDT": 500})
    assert report.outcomes["SOLUSDT"] == "DATA_ERROR" and report.outcomes["ETHUSDT"].startswith(
        "SIGNAL:"
    )
