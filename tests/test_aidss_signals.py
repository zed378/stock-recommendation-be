"""The crypto signal worker (ADR-065): config, universe, scoring with the stock-pick criteria, the
AI review as a veto, the payload, the worker's fail-closed behaviour, and the receiver's handshake.

Nothing here touches a network or an AI provider: market data comes from `httpx.MockTransport`, the
reviewer is a function, and the Socket.IO server is exercised over loopback only."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from aidss.domain.types import Candle
from aidss.screener.criteria import CRITERIA_BY_HORIZON, Horizon
from aidss_signals.ai_review import (
    AiUnavailable,
    Verdict,
    build_dossier,
    build_messages,
    gateway_reviewer,
    parse_verdict,
)
from aidss_signals.config import ConfigError, load_config
from aidss_signals.market import MarketData, MarketDataError, is_plain_coin
from aidss_signals.payload import STRATEGY, build_signal
from aidss_signals.screen import btc_bias, mechanical_levels, score_asset
from aidss_signals.worker import State, choose_universe, run_pass

NOW = datetime(2026, 11, 21, 0, 10, tzinfo=UTC)  # ten minutes after a daily close
ENV = {
    "AIDSS_SIGNALS_ENABLED": "true",
    "AIDSS_SIGNALS_SYMBOLS": "ETHUSDT,SOLUSDT",
    "AIDSS_SIGNALS_MIN_QUOTE_VOLUME_USDT": "1000000",
    "AIDSS_SIGNALS_HORIZONS": "14d,30d",
    "AIDSS_SIGNALS_MIN_SCORE_RATIO": "0.8",
    "AIDSS_SIGNALS_ATR_STOP_MULTIPLE": "2",
    "AIDSS_SIGNALS_TP_R1": "1.5",
    "AIDSS_SIGNALS_TP_R2": "2.5",
    "AIDSS_SIGNALS_TP_R3": "4",
    "AIDSS_SIGNALS_AI_MIN_SCORE": "70",
    "AIDSS_SIGNALS_AI_MAX_CALLS": "10",
}


def candles(n: int, drift: float, seed: int = 1, end: datetime = NOW) -> list[Candle]:
    rng, price = random.Random(seed), 100.0
    start = end.replace(hour=0, minute=0) - timedelta(days=n)
    out = []
    for i in range(n):
        price *= 1 + drift + rng.uniform(-0.01, 0.01)
        out.append(
            Candle(
                start + timedelta(days=i),
                D(str(round(price * 0.995, 6))),
                D(str(round(price * 1.01, 6))),
                D(str(round(price * 0.99, 6))),
                D(str(round(price, 6))),
                D(str(1000 + rng.randint(0, 500))),
            )
        )
    return out


def rows(cs: list[Candle], closed: bool = True) -> list[list[object]]:
    out = []
    for c in cs:
        o = int(c.timestamp.timestamp() * 1000)
        out.append(
            [
                o,
                str(c.open),
                str(c.high),
                str(c.low),
                str(c.close),
                str(c.volume),
                o + 86_400_000 - 1,
            ]
        )
    if not closed:  # a still-forming candle at the end
        o = int(NOW.replace(hour=0, minute=0).timestamp() * 1000)
        out.append([o, "1", "2", "1", "1.5", "1", o + 86_400_000 - 1])
    return out


def market(per_symbol: dict[str, object], tickers: list[dict[str, str]]) -> MarketData:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/ticker/24hr":
            return httpx.Response(200, json=tickers)
        symbol = request.url.params["symbol"]
        body = per_symbol[symbol]
        return httpx.Response(500) if isinstance(body, int) else httpx.Response(200, json=body)

    return MarketData(
        "https://x", httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )


def tick(symbol: str, volume: str) -> dict[str, str]:
    return {"symbol": symbol, "quoteVolume": volume}


GOOD = Verdict(82, "TAKE", "MEDIUM", ("trend and structure agree",), ("extended",))


# ---------------------------------------------------------------------------------- config


def test_off_unless_enabled_and_every_number_is_required() -> None:
    assert load_config({}) is None
    assert load_config({"AIDSS_SIGNALS_ENABLED": "false"}) is None
    cfg = load_config(ENV)
    assert cfg is not None and cfg.mode == "SHADOW" and cfg.horizons == ("14d", "30d")
    for name in [k for k in ENV if k not in ("AIDSS_SIGNALS_ENABLED", "AIDSS_SIGNALS_SYMBOLS")]:
        env = {k: v for k, v in ENV.items() if k != name}
        with pytest.raises(ConfigError, match=name.removeprefix("AIDSS_SIGNALS_")):
            load_config(env)


def test_top_n_defaults_to_five_and_the_owner_can_set_it() -> None:
    assert load_config(ENV).top_n == 5
    assert load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "12"}).top_n == 12
    assert load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "0"}).top_n == 0
    for bad in ("-1", "2.5", "x", "51"):
        with pytest.raises(ConfigError, match="TOP_N"):
            load_config({**ENV, "AIDSS_SIGNALS_TOP_N": bad})
    env = {**ENV, "AIDSS_SIGNALS_SYMBOLS": "", "AIDSS_SIGNALS_TOP_N": "0"}
    with pytest.raises(ConfigError, match="nothing to scan"):
        load_config(env)


def test_invalid_values_are_all_reported_together() -> None:
    env = {
        **ENV,
        "AIDSS_SIGNALS_SYMBOLS": "btc/usdt",
        "AIDSS_SIGNALS_HORIZONS": "3d",
        "AIDSS_SIGNALS_MIN_SCORE_RATIO": "1.5",
        "AIDSS_SIGNALS_TP_R2": "1",
        "AIDSS_SIGNALS_MODE": "LIVE",
    }
    with pytest.raises(ConfigError) as err:
        load_config(env)
    msg = str(err.value)
    for part in ("SYMBOLS", "HORIZONS", "MIN_SCORE_RATIO", "TP_R1 < TP_R2", "MODE"):
        assert part in msg


def test_publish_needs_confirmation_and_a_long_token_and_the_token_is_never_shown() -> None:
    soft = load_config(
        {**ENV, "AIDSS_SIGNALS_MODE": "PUBLISH", "AIDSS_SIGNALS_CLIENT_TOKEN": "x" * 20}
    )
    assert soft.mode == "SHADOW" and soft.notes  # no confirmation: stays in SHADOW and says so
    on = load_config(
        {
            **ENV,
            "AIDSS_SIGNALS_MODE": "PUBLISH",
            "AIDSS_SIGNALS_CONFIRM_PUBLISH": "yes",
            "AIDSS_SIGNALS_CLIENT_TOKEN": "secret-token-123456",
        }
    )
    assert on.mode == "PUBLISH" and "secret-token-123456" not in repr(on)
    with pytest.raises(ConfigError, match="CLIENT_TOKEN"):
        load_config(
            {
                **ENV,
                "AIDSS_SIGNALS_MODE": "PUBLISH",
                "AIDSS_SIGNALS_CONFIRM_PUBLISH": "yes",
                "AIDSS_SIGNALS_CLIENT_TOKEN": "short",
            }
        )


# ---------------------------------------------------------------------- market and universe


def test_plain_coin_filter_drops_stablecoins_fiat_and_leveraged_tokens() -> None:
    for ok in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "UPUSDT", "SUPERUSDT"):
        assert is_plain_coin(ok), ok
    for bad in (
        "USDCUSDT",
        "FDUSDUSDT",
        "EURUSDT",
        "BTCUPUSDT",
        "ETHDOWNUSDT",
        "BTCBTC",
        "USDTUSDT",
        "DAIUSDT",
    ):
        assert not is_plain_coin(bad), bad


def test_closed_candles_only_and_bad_data_is_refused() -> None:
    cs = candles(30, 0.001)
    m = market({"ETHUSDT": rows(cs, closed=False)}, [])
    out = m.daily_candles("ETHUSDT", NOW)
    assert len(out) == 30 and all(c.timestamp < NOW.replace(hour=0, minute=0) for c in out)
    for body in (
        {"no": "list"},
        [[1, "a", "b", "c", "d", "e", 9]],
        [[1, "5", "4", "6", "5", "1", 9]],
        [[1, "5", "6", "4", "5", "1", 9], [1, "5", "6", "4", "5", "1", 9]],
        500,
    ):
        with pytest.raises(MarketDataError):
            market({"ETHUSDT": body}, []).daily_candles("ETHUSDT", NOW)


def test_universe_is_the_fixed_list_plus_top_n_above_the_volume_floor() -> None:
    cfg = load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "2"})
    volumes = {
        "BTCUSDT": D(9_000_000_000),
        "ETHUSDT": D(5_000_000_000),
        "SOLUSDT": D(500_000),
        "DOGEUSDT": D(3_000_000_000),
        "XRPUSDT": D(2_000_000_000),
    }
    chosen, dropped = choose_universe(cfg, volumes)
    # the two biggest by volume are BTC and ETH; ETH is also in the fixed list, so it counts once
    assert chosen == ["BTCUSDT", "ETHUSDT"]
    assert dropped == {"SOLUSDT": "below_min_volume"}
    wider, _ = choose_universe(load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "3"}), volumes)
    assert wider == ["BTCUSDT", "DOGEUSDT", "ETHUSDT"]
    none, drop = choose_universe(
        load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "0"}), {"BTCUSDT": D(1)}
    )
    assert none == [] and set(drop) == {"ETHUSDT", "SOLUSDT"}


# ------------------------------------------------------------------------------ scoring


def test_a_coin_is_scored_with_the_stock_pick_criteria_unchanged() -> None:
    s = score_asset(candles(260, 0.006), ("14d", "30d"))
    assert s.eligible and s.ratio > 0.8
    keys = {h: {c.key for c in CRITERIA_BY_HORIZON[Horizon(h)]} for h in ("14d", "30d")}
    for h in (
        "14d",
        "30d",
    ):  # every key is one of the platform's own, and met + failed cover them all
        assert set(s.met[h]) | set(s.failed[h]) == keys[h] and not s.unevaluable[h]
    maxima = sum(c.weight for h in ("14d", "30d") for c in CRITERIA_BY_HORIZON[Horizon(h)])
    assert s.max_score == pytest.approx(maxima)
    down = score_asset(candles(260, -0.006), ("14d", "30d"))
    assert down.eligible and down.ratio < 0.5 < s.ratio


def test_short_history_is_not_scored_rather_than_scored_low() -> None:
    s = score_asset(candles(100, 0.006), ("14d", "30d"))
    assert not s.eligible and s.reason.startswith("history_too_short") and s.ratio == 0.0


def test_btc_bias_and_mechanical_levels() -> None:
    assert btc_bias(candles(260, 0.006)) == "bullish"
    assert btc_bias(candles(260, -0.006)) == "bearish"
    assert btc_bias(candles(50, 0.01)) == ""
    lv = mechanical_levels(100.0, 4.0, 2.0, (1.5, 2.5, 4.0))
    assert lv["stop"] == 92.0 and lv["tp1"] == 112.0 and lv["tp2"] == 120.0 and lv["tp3"] == 132.0
    assert lv["stop"] < lv["entry"] < lv["tp1"] < lv["tp2"] < lv["tp3"]
    assert mechanical_levels(100.0, None, 2.0, (1.5, 2.5, 4.0)) is None
    assert mechanical_levels(100.0, 60.0, 2.0, (1.5, 2.5, 4.0)) is None  # stop would be below zero


# -------------------------------------------------------------------------------- AI review


def test_verdict_parsing_is_strict() -> None:
    ok = json.dumps(
        {"score": 82, "verdict": "TAKE", "confidence": "MEDIUM", "reasons": ["a"], "risks": []}
    )
    assert parse_verdict(ok).score == 82
    assert parse_verdict("```json\n" + ok + "\n```").verdict == "TAKE"
    assert parse_verdict("Here is my view: " + ok).verdict == "TAKE"
    base = {"score": 82, "verdict": "TAKE", "confidence": "LOW", "reasons": [], "risks": []}
    for bad in (
        "nope",
        "[]",
        "{}",
        json.dumps({**base, "score": 101}),
        json.dumps({**base, "score": 7.5}),
        json.dumps({**base, "score": True}),
        json.dumps({**base, "verdict": "BUY"}),
        json.dumps({**base, "confidence": "SURE"}),
        json.dumps({**base, "reasons": list("abcd")}),
        json.dumps({**base, "risks": [1]}),
    ):
        with pytest.raises(AiUnavailable):
            parse_verdict(bad)


def test_the_prompt_carries_only_data_and_fixed_phrases() -> None:
    s = score_asset(candles(260, 0.006), ("14d", "30d"))
    lv = mechanical_levels(s.close, s.atr, 2.0, (1.5, 2.5, 4.0))
    d = build_dossier("ETHUSDT", s, lv, "bullish", "2026-11-20")
    system, user = (m.content for m in build_messages(d))
    assert "ignore" in system and "instruction" in system
    assert "ETHUSDT" in user and "bullish" in user and "met" in d and "not_met" in d
    described = {c.describes for h in ("14d", "30d") for c in CRITERIA_BY_HORIZON[Horizon(h)]}
    for phrases in list(d["met"].values()) + list(d["not_met"].values()):
        assert set(phrases) <= described  # every sentence is a criterion description from the code


def test_the_gateway_reviewer_turns_every_failure_into_unavailable() -> None:
    class Boom:
        def complete(self, request):
            raise RuntimeError("provider down sk-secret")

    class Garbage:
        def complete(self, request):
            return type("R", (), {"content": "not json"})()

    class Fine:
        seen = None

        def complete(self, request):
            Fine.seen = request
            return type(
                "R",
                (),
                {
                    "content": json.dumps(
                        {
                            "score": 90,
                            "verdict": "TAKE",
                            "confidence": "HIGH",
                            "reasons": [],
                            "risks": [],
                        }
                    )
                },
            )()

    with pytest.raises(AiUnavailable) as err:
        gateway_reviewer(Boom())({"symbol": "X"})
    assert "sk-secret" not in str(err.value)
    with pytest.raises(AiUnavailable):
        gateway_reviewer(Garbage())({"symbol": "X"})
    assert gateway_reviewer(Fine())({"symbol": "X"}).score == 90
    assert (
        Fine.seen.expects_json
        and Fine.seen.temperature == 0.0
        and Fine.seen.agent == "crypto_signal_review"
    )


# ----------------------------------------------------------------------- payload and worker


def test_the_payload_matches_the_receivers_contract() -> None:
    s = score_asset(candles(260, 0.006), ("14d", "30d"))
    lv = mechanical_levels(s.close, s.atr, 2.0, (1.5, 2.5, 4.0))
    p = build_signal("ETHUSDT", "2026-11-20", s, lv, GOOD, "bullish")
    assert (
        p["id"] == "aidss-ETHUSDT-2026-11-20" and p["side"] == "LONG" and p["strategy"] == STRATEGY
    )
    assert p["sl"] < p["entryPrice"] < p["tp1"] < p["tp2"] < p["tp3"]
    assert isinstance(p["score"], int) and 0 <= p["score"] <= 100 and p["btcTrendBias"] == "bullish"
    assert p["analytics"]["ai"]["score"] == 82 and set(p["analytics"]["horizons"]) == {"14d", "30d"}
    assert json.loads(json.dumps(p)) == p  # plain JSON, no Decimal or NaN


def run(cfg, mkt, review, state=None):
    published, records, logs = [], [], []
    report = run_pass(
        cfg,
        mkt,
        review,
        published.append,
        NOW,
        state or State(None),
        records.append,
        lambda lvl, msg: logs.append(msg),
    )
    return report, published, records, logs


def universe_market():
    up, down, short = candles(260, 0.006, 1), candles(260, -0.006, 2), candles(100, 0.006, 3)
    tickers = [
        tick("ETHUSDT", "5000000000"),
        tick("SOLUSDT", "4000000000"),
        tick("BTCUSDT", "9000000000"),
    ]
    return market({"BTCUSDT": rows(up), "ETHUSDT": rows(up), "SOLUSDT": rows(down)}, tickers), short


PUBLISH_ENV = {
    **ENV,
    "AIDSS_SIGNALS_TOP_N": "0",
    "AIDSS_SIGNALS_MODE": "PUBLISH",
    "AIDSS_SIGNALS_CONFIRM_PUBLISH": "yes",
    "AIDSS_SIGNALS_CLIENT_TOKEN": "t" * 20,
}


def test_only_a_strong_coin_the_ai_takes_is_published() -> None:
    cfg = load_config(PUBLISH_ENV)
    mkt, _ = universe_market()
    report, published, records, _ = run(cfg, mkt, lambda d: GOOD)
    assert report.outcomes == {"ETHUSDT": "SIGNAL", "SOLUSDT": "BELOW_THRESHOLD"}
    assert [s["symbol"] for s in published] == ["ETHUSDT"] and report.ai_calls == 1
    assert {r["outcome"] for r in records} == {"SIGNAL", "BELOW_THRESHOLD"}


def test_shadow_mode_publishes_nothing() -> None:
    cfg = load_config({**ENV, "AIDSS_SIGNALS_TOP_N": "0"})
    mkt, _ = universe_market()
    report, published, _, logs = run(cfg, mkt, lambda d: GOOD)
    assert report.outcomes["ETHUSDT"] == "SIGNAL" and published == []
    assert any("SHADOW" in line for line in logs)


def test_the_ai_can_only_say_no() -> None:
    cfg = load_config(PUBLISH_ENV)
    mkt, _ = universe_market()
    for verdict, outcome in (
        (Verdict(95, "SKIP", "HIGH", (), ()), "AI_SKIP"),
        (Verdict(60, "TAKE", "LOW", (), ()), "AI_BELOW_MIN"),
    ):
        report, published, _, _ = run(cfg, mkt, lambda d, v=verdict: v)
        assert published == [] and report.outcomes["ETHUSDT"] == outcome


def test_no_review_means_no_signal_and_the_coin_is_not_retried_that_day() -> None:
    cfg = load_config(PUBLISH_ENV)
    mkt, _ = universe_market()
    calls = []

    def down(d):
        calls.append(1)
        raise AiUnavailable("down")

    state = State(None)
    report, published, _, _ = run(cfg, mkt, down, state)
    assert published == [] and report.outcomes["ETHUSDT"] == "AI_UNAVAILABLE"
    report2, published2, _, _ = run(cfg, mkt, lambda d: GOOD, state)
    assert report2.outcomes["ETHUSDT"] == "ALREADY_DECIDED" and published2 == [] and len(calls) == 1


def test_a_coin_is_decided_once_per_daily_close_and_survives_a_restart(tmp_path) -> None:
    cfg = load_config({**PUBLISH_ENV, "AIDSS_SIGNALS_DATA_DIR": str(tmp_path)})
    mkt, _ = universe_market()
    _, first, _, _ = run(cfg, mkt, lambda d: GOOD, State(cfg.state_path))
    _, second, _, _ = run(cfg, mkt, lambda d: GOOD, State(cfg.state_path))  # a fresh process
    assert len(first) == 1 and second == []


def test_a_short_history_coin_is_ineligible_and_the_ai_is_not_asked() -> None:
    cfg = load_config(PUBLISH_ENV)
    short = candles(100, 0.006)
    mkt = market(
        {"BTCUSDT": rows(candles(260, 0.006)), "ETHUSDT": rows(short), "SOLUSDT": rows(short)},
        [tick("ETHUSDT", "5000000000"), tick("SOLUSDT", "4000000000")],
    )
    report, published, _, _ = run(cfg, mkt, lambda d: pytest.fail("the AI must not be asked"))
    assert published == [] and report.ai_calls == 0
    assert all(v.startswith("INELIGIBLE") for v in report.outcomes.values())


def test_btc_failure_stops_the_whole_pass_and_one_bad_coin_does_not() -> None:
    cfg = load_config(PUBLISH_ENV)
    up = candles(260, 0.006)
    tickers = [tick("ETHUSDT", "5000000000"), tick("SOLUSDT", "4000000000")]
    no_btc = market({"BTCUSDT": 500, "ETHUSDT": rows(up), "SOLUSDT": rows(up)}, tickers)
    report, published, _, _ = run(cfg, no_btc, lambda d: GOOD)
    assert (
        published == []
        and report.errors
        and not report.outcomes.get("ETHUSDT", "").startswith("SIGNAL")
    )
    one_bad = market({"BTCUSDT": rows(up), "ETHUSDT": 500, "SOLUSDT": rows(up)}, tickers)
    report, published, _, _ = run(cfg, one_bad, lambda d: GOOD)
    assert report.outcomes["ETHUSDT"] == "DATA_ERROR" and [s["symbol"] for s in published] == [
        "SOLUSDT"
    ]


def test_the_ai_call_budget_is_respected() -> None:
    cfg = load_config({**PUBLISH_ENV, "AIDSS_SIGNALS_AI_MAX_CALLS": "1"})
    up = candles(260, 0.006)
    mkt = market(
        {"BTCUSDT": rows(up), "ETHUSDT": rows(up), "SOLUSDT": rows(up)},
        [tick("ETHUSDT", "5000000000"), tick("SOLUSDT", "4000000000")],
    )
    report, published, _, _ = run(cfg, mkt, lambda d: GOOD)
    assert report.ai_calls == 1 and len(published) == 1
    assert sorted(report.outcomes.values()) == ["AI_BUDGET", "SIGNAL"]


# ----------------------------------------------------------------------------- receiver


def test_the_hub_refuses_a_wrong_token_and_delivers_signals_and_collects_acks() -> None:
    import socketio
    import uvicorn

    from aidss_signals.server import SignalHub

    async def scenario() -> None:
        hub = SignalHub("a-long-enough-token-1")
        server = uvicorn.Server(
            uvicorn.Config(hub.app, host="127.0.0.1", port=0, log_level="error")
        )
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        bad = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await bad.connect(url, auth={"token": "wrong"}, wait_timeout=5)
        none = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await none.connect(url, wait_timeout=5)

        client = socketio.AsyncClient()
        received: list[dict] = []

        @client.on("new_signal")
        async def on_signal(data) -> None:
            received.append(data)
            await client.emit(
                "signal_ack", {"signalId": data["id"], "stage": "RECEIVED", "junk": "x"}
            )

        await client.connect(url, auth={"token": "a-long-enough-token-1"}, wait_timeout=5)
        await asyncio.sleep(0.1)
        await hub.publish({"id": "aidss-ETHUSDT-2026-11-20", "symbol": "ETHUSDT"})
        for _ in range(50):
            if hub.acks:
                break
            await asyncio.sleep(0.05)
        assert received == [{"id": "aidss-ETHUSDT-2026-11-20", "symbol": "ETHUSDT"}]
        assert hub.acks == [
            {"signalId": "aidss-ETHUSDT-2026-11-20", "stage": "RECEIVED"}
        ]  # unknown fields dropped
        await client.disconnect()
        server.should_exit = True
        await task

    asyncio.run(scenario())


def test_a_hub_needs_a_real_token() -> None:
    from aidss_signals.server import SignalHub

    with pytest.raises(ValueError):
        SignalHub("short")
