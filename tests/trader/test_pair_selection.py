"""ALL, the pair catalogue and the owner's pair groups (ADR-058)."""

from __future__ import annotations

from decimal import Decimal as D

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.api import ApiContext, create_app
from aidss_trader.api.app import allowlist_loosens
from aidss_trader.auth import TokenVerifier
from aidss_trader.auth.stepup import StepUp
from aidss_trader.connector.types import MarketSummary, PairInfo
from aidss_trader.db.base import Base
from aidss_trader.killswitch import KillSwitch
from aidss_trader.notify import Notifier
from aidss_trader.runtime.pair_selection import resolve_all, spread_pct
from aidss_trader.runtime.settings_store import (
    Allowlist,
    LiquidityFilter,
    get_allowlist,
    get_pair_groups,
    set_allowlist,
    set_pair_groups,
)
from tests.trader.test_connector_contract import Env
from tests.trader.test_runtime_wiring import World
from tests.trader.test_t5_operator_surface import T0, THRESHOLDS, USERS, RecordingChannel, Sent

LIQ = LiquidityFilter(D("1000000000"), D("0.5"))


def info(pair: str, *, maintenance: bool = False, suspended: bool = False) -> PairInfo:
    return PairInfo(
        pair=pair,
        ticker_id=pair.lower(),
        base_asset="IDR",
        quote_asset=pair[:-3],
        quantity_increment=None,
        min_base_idr=D("10000"),
        min_traded_qty=None,
        maintenance=maintenance,
        suspended=suspended,
        maker_fee_pct=None,
        taker_fee_pct=None,
    )


def summary(pair: str, volume: str | None, bid: str = "1000", ask: str = "1002") -> MarketSummary:
    return MarketSummary(
        pair=pair,
        last=D(bid),
        bid=D(bid),
        ask=D(ask),
        quote_volume_24h=None if volume is None else D(volume),
    )


# ------------------------------------------------------------------------------ resolve_all


def test_all_keeps_liquid_trading_markets_best_volume_first_up_to_n() -> None:
    pairs = [info(p) for p in ("AAAIDR", "BBBIDR", "CCCIDR", "DDDIDR")]
    sums = {
        "AAAIDR": summary("AAAIDR", "5000000000"),
        "BBBIDR": summary("BBBIDR", "9000000000"),
        "CCCIDR": summary("CCCIDR", "2000000000"),
        "DDDIDR": summary("DDDIDR", "3000000000"),
    }
    assert resolve_all(pairs, sums, LIQ, 3) == ("BBBIDR", "AAAIDR", "DDDIDR")
    assert resolve_all(pairs, sums, LIQ, 10) == ("BBBIDR", "AAAIDR", "DDDIDR", "CCCIDR")


def test_all_excludes_what_fails_or_is_unknown() -> None:
    pairs = [
        info("OKIDR"),
        info("THINIDR"),
        info("WIDEIDR"),
        info("MAINTIDR", maintenance=True),
        info("HALTIDR", suspended=True),
        info("NOSUMIDR"),
        info("NOVOLIDR"),
        info("CROSSEDIDR"),
    ]
    sums = {
        "OKIDR": summary("OKIDR", "2000000000"),
        "THINIDR": summary("THINIDR", "999999999"),
        "WIDEIDR": summary("WIDEIDR", "2000000000", bid="1000", ask="1010"),  # 1% > 0.5%
        "MAINTIDR": summary("MAINTIDR", "2000000000"),
        "HALTIDR": summary("HALTIDR", "2000000000"),
        "NOVOLIDR": summary("NOVOLIDR", None),
        "CROSSEDIDR": summary("CROSSEDIDR", "2000000000", bid="1002", ask="1000"),
    }
    assert resolve_all(pairs, sums, LIQ, 50) == ("OKIDR",)


def test_all_is_empty_without_the_owners_numbers() -> None:
    pairs = [info("AAAIDR")]
    sums = {"AAAIDR": summary("AAAIDR", "5000000000")}
    assert resolve_all(pairs, sums, LiquidityFilter(None, D("1")), 5) == ()
    assert resolve_all(pairs, sums, LiquidityFilter(D("1"), None), 5) == ()
    assert resolve_all(pairs, sums, LIQ, 0) == ()


def test_ties_break_by_name_and_the_spread_formula_is_ask_over_bid() -> None:
    pairs = [info("ZZZIDR"), info("AAAIDR")]
    sums = {p: summary(p, "2000000000") for p in ("ZZZIDR", "AAAIDR")}
    assert resolve_all(pairs, sums, LIQ, 5) == ("AAAIDR", "ZZZIDR")
    assert spread_pct(summary("X", "1", bid="1000", ask="1005")) == D("0.5")


# ---------------------------------------------------------------------------------- storage


def _session():
    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_the_allowlist_round_trips_all_and_its_number() -> None:
    factory = _session()
    with factory() as s:
        assert get_allowlist(s).all_pairs is False and get_allowlist(s).all_active is False
        set_allowlist(
            s, Allowlist(("BTCIDR",), LIQ, all_pairs=True, max_pairs=20), by="u1"
        )
        s.commit()
        got = get_allowlist(s)
        assert got.all_pairs and got.max_pairs == 20 and got.all_active and got.has_scope
        # ALL without its number, or without the liquidity numbers, selects nothing.
        assert not Allowlist((), LIQ, all_pairs=True, max_pairs=None).all_active
        assert not Allowlist((), LiquidityFilter(), all_pairs=True, max_pairs=5).all_active


def test_groups_are_stored_uppercased_and_sorted() -> None:
    factory = _session()
    with factory() as s:
        assert get_pair_groups(s) == {}
        set_pair_groups(s, {"Majors": ("ethidr", "BTCIDR")}, by="u1")
        s.commit()
        assert get_pair_groups(s) == {"Majors": ("ETHIDR", "BTCIDR")}


# -------------------------------------------------------------------------------- loosening


@pytest.mark.parametrize(
    ("old", "new", "loosens"),
    [
        (Allowlist((), LIQ), Allowlist((), LIQ, all_pairs=True, max_pairs=10), True),
        (
            Allowlist((), LIQ, all_pairs=True, max_pairs=10),
            Allowlist((), LIQ, all_pairs=True, max_pairs=20),
            True,
        ),
        (
            Allowlist((), LIQ, all_pairs=True, max_pairs=10),
            Allowlist((), LIQ, all_pairs=True, max_pairs=5),
            False,
        ),
        (Allowlist((), LIQ, all_pairs=True, max_pairs=10), Allowlist((), LIQ), False),
        (
            Allowlist((), LIQ, all_pairs=True, max_pairs=None),
            Allowlist((), LIQ, all_pairs=True, max_pairs=3),
            True,
        ),
        (Allowlist(("A1IDR",), LIQ), Allowlist(("A1IDR", "B2IDR"), LIQ), True),
    ],
)
def test_switching_all_on_or_raising_n_needs_a_step_up(old, new, loosens) -> None:
    assert allowlist_loosens(old, new) is loosens


# ------------------------------------------------------------------------------------- API


class Rig:
    def __init__(self, *, exchange: bool = True) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        ).execution_options(schema_translate_map={"trading": None})
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.env = Env()
        m = self.env.mock
        m.pairs = [
            {
                "id": "btcidr",
                "symbol": "BTCIDR",
                "base_currency": "idr",
                "traded_currency": "btc",
                "ticker_id": "btc_idr",
                "trade_min_base_currency": 10000,
                "trade_min_traded_currency": 0.0001,
                "is_maintenance": 0,
                "is_market_suspended": 0,
            },
            {
                "id": "ethidr",
                "symbol": "ETHIDR",
                "base_currency": "idr",
                "traded_currency": "eth",
                "ticker_id": "eth_idr",
                "trade_min_base_currency": 10000,
                "trade_min_traded_currency": 0.0001,
                "is_maintenance": 0,
                "is_market_suspended": 1,
            },
            {
                "id": "btcusdt",
                "symbol": "BTCUSDT",
                "base_currency": "usdt",
                "traded_currency": "btc",
                "ticker_id": "btc_usdt",
                "trade_min_base_currency": 5,
                "trade_min_traded_currency": 0.0001,
            },
        ]
        m.summaries = {
            "btc_idr": {"buy": "1000", "sell": "1001", "last": "1000", "vol_idr": "9000000000"},
            "eth_idr": {"buy": "50", "sell": "50", "last": "50", "vol_idr": "100"},
            "btc_usdt": {"buy": "1", "sell": "1", "last": "1", "vol_idr": "1"},
        }

        def me(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/auth/login":
                return httpx.Response(200, json={"access_token": "tok-trader"})
            who = USERS.get(req.headers.get("authorization", "")[7:])
            if who is None:
                return httpx.Response(401)
            return httpx.Response(200, json={"id": who[0], "role": who[1]})

        transport = httpx.MockTransport(me)
        verifier = TokenVerifier("https://a.test", timeout_s=2, transport=transport)
        self.chan = RecordingChannel()
        ctx = ApiContext(
            session_factory=self.factory,
            verifier=verifier,
            stepup=lambda s: StepUp(s, "https://a.test", verifier, transport=transport),
            notifier=lambda s: Notifier(s, self.chan),
            killswitch=lambda s: KillSwitch(s, self.env.client),
            submit_approved=lambda s, i: Sent()(),
            thresholds=lambda: THRESHOLDS,
            freshness=lambda: (T0, False),
            stored_exchange_client=(lambda: self.env.client) if exchange else (lambda: None),
        )
        self.http = TestClient(create_app(ctx))
        self.n = 0

    def call(self, method: str, path: str, token: str = "tok-trader", *, body=None, step_up=None):
        headers = {"Authorization": f"Bearer {token}"}
        if method != "GET":
            self.n += 1
            headers["Idempotency-Key"] = f"k{self.n}"
        if step_up:
            headers["X-Step-Up"] = step_up
        return self.http.request(method, "/trader/v1" + path, headers=headers, json=body)

    def grant(self) -> str:
        r = self.call(
            "POST", "/stepup", body={"email": "o@x", "password": "pw", "scope": "RAISE_LIMIT"}
        )
        assert r.status_code == 200, r.text
        return r.json()["data"]["grant"]


def test_the_catalogue_lists_idr_markets_with_volume_status_and_no_other_quote() -> None:
    rig = Rig()
    r = rig.call("GET", "/pairs-catalog")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["pairs"]
    assert [x["pair"] for x in rows] == ["BTCIDR", "ETHIDR"]  # no BTCUSDT; best volume first
    btc, eth = rows
    assert btc["trading"] is True and btc["quote_volume_24h_idr"] == "9000000000"
    assert btc["spread_pct"] == "0.1000" and btc["min_order_idr"] == "10000"
    assert eth["trading"] is False  # suspended is shown, not hidden


def test_the_catalogue_says_so_when_no_exchange_is_configured() -> None:
    r = Rig(exchange=False).call("GET", "/pairs-catalog")
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_exchange"


def test_groups_are_saved_validated_and_trade_nothing() -> None:
    rig = Rig()
    ok = rig.call(
        "PUT",
        "/pair-groups",
        body={"groups": [{"name": "  Large   caps ", "pairs": ["ethidr", "BTCIDR", "btcidr"]}]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["groups"] == [{"name": "Large caps", "pairs": ["BTCIDR", "ETHIDR"]}]
    assert rig.call("GET", "/pair-groups").json()["data"] == ok.json()["data"]
    # Saving a group needs no step-up and does not touch the allowlist.
    with rig.factory() as s:
        assert get_allowlist(s).pairs == ()


@pytest.mark.parametrize(
    "groups",
    [
        [{"name": "", "pairs": ["BTCIDR"]}],
        [{"name": "x" * 41, "pairs": ["BTCIDR"]}],
        [{"name": "A", "pairs": ["BTCIDR"]}, {"name": "a", "pairs": ["ETHIDR"]}],
        [{"name": "A", "pairs": []}],
        [{"name": "A", "pairs": ["BTCUSDT"]}],
    ],
)
def test_bad_groups_are_refused(groups) -> None:
    r = Rig().call("PUT", "/pair-groups", body={"groups": groups})
    assert r.status_code == 400, r.text


def test_a_viewer_can_read_but_not_change_groups() -> None:
    rig = Rig()
    assert rig.call("GET", "/pair-groups", "tok-viewer").status_code == 200
    assert (
        rig.call("PUT", "/pair-groups", "tok-viewer", body={"groups": []}).status_code == 403
    )


def test_switching_all_on_needs_a_step_up_and_then_is_active() -> None:
    rig = Rig()
    body = {
        "pairs": [],
        "min_quote_volume_24h_idr": "1000000000",
        "max_spread_pct": "0.5",
        "all_pairs": True,
        "max_pairs": 10,
    }
    refused = rig.call("PUT", "/allowlist", body=body)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "step_up_required"
    done = rig.call("PUT", "/allowlist", body=body, step_up=rig.grant())
    assert done.status_code == 200, done.text
    assert done.json()["data"]["active"] is True
    got = rig.call("GET", "/allowlist").json()["data"]
    assert got["all_pairs"] is True and got["max_pairs"] == 10 and got["active"] is True


def test_all_without_its_number_is_not_active() -> None:
    rig = Rig()
    body = {
        "pairs": [],
        "min_quote_volume_24h_idr": "1000000000",
        "max_spread_pct": "0.5",
        "all_pairs": True,
        "max_pairs": None,
    }
    r = rig.call("PUT", "/allowlist", body=body, step_up=rig.grant())
    assert r.status_code == 200, r.text
    assert r.json()["data"]["active"] is False


def test_n_above_the_ceiling_is_refused() -> None:
    rig = Rig()
    body = {"pairs": [], "all_pairs": True, "max_pairs": 5000}
    assert rig.call("PUT", "/allowlist", body=body, step_up=rig.grant()).status_code in (400, 422)


# ------------------------------------------------------------------------------- the runtime


def _all_world(max_pairs: int = 2) -> World:
    w = World("PAPER")
    m = w.env.mock
    m.pairs = [
        {
            "id": p.lower(),
            "symbol": p,
            "base_currency": "idr",
            "traded_currency": p[:-3].lower(),
            "ticker_id": f"{p[:-3].lower()}_idr",
            "trade_min_base_currency": 10000,
            "trade_min_traded_currency": 0.0001,
            "is_maintenance": 0,
            "is_market_suspended": 0,
        }
        for p in ("BTCIDR", "AAAIDR", "BBBIDR", "CCCIDR")
    ]
    m.summaries = {
        "btc_idr": {"buy": "1000", "sell": "1001", "last": "1000", "vol_idr": "9000000000"},
        "aaa_idr": {"buy": "1000", "sell": "1001", "last": "1000", "vol_idr": "5000000000"},
        "bbb_idr": {"buy": "1000", "sell": "1001", "last": "1000", "vol_idr": "3000000000"},
        "ccc_idr": {"buy": "1000", "sell": "1001", "last": "1000", "vol_idr": "2000000000"},
    }
    with w.factory() as s:
        set_allowlist(s, Allowlist((), LIQ, all_pairs=True, max_pairs=max_pairs), by="owner")
        s.commit()
    return w


def test_the_runtime_watches_the_pairs_all_selects_plus_the_named_ones() -> None:
    w = _all_world(max_pairs=2)
    with w.factory() as s:
        set_allowlist(
            s, Allowlist(("CCCIDR",), LIQ, all_pairs=True, max_pairs=2), by="owner"
        )
        s.commit()
        assert w.runtime._active_pairs(s) == ("AAAIDR", "BTCIDR", "CCCIDR")


def test_all_is_not_applied_without_its_number_and_a_filter() -> None:
    w = _all_world()
    with w.factory() as s:
        set_allowlist(s, Allowlist((), LIQ, all_pairs=True, max_pairs=None), by="owner")
        s.commit()
        assert w.runtime._active_pairs(s) == ()
        set_allowlist(s, Allowlist((), LiquidityFilter(), all_pairs=True, max_pairs=5), by="owner")
        s.commit()
        assert w.runtime._active_pairs(s) == ()


def test_the_selection_is_refreshed_only_every_five_minutes_and_on_a_changed_setting() -> None:
    w = _all_world(max_pairs=1)
    mock = w.env.mock
    with w.factory() as s:
        assert w.runtime._active_pairs(s) == ("BTCIDR",)
        mock.summaries["aaa_idr"]["vol_idr"] = "99000000000"  # AAA overtakes BTC
        mock.advance(60_000)
        assert w.runtime._active_pairs(s) == ("BTCIDR",)  # cached: one minute is too soon
        mock.advance(250_000)
        assert w.runtime._active_pairs(s) == ("AAAIDR",)  # five minutes on
        set_allowlist(s, Allowlist((), LIQ, all_pairs=True, max_pairs=2), by="owner")
        s.commit()
        assert w.runtime._active_pairs(s) == ("AAAIDR", "BTCIDR")  # changed N: at once


def test_a_failed_refresh_keeps_the_list_for_a_while_then_drops_it() -> None:
    w = _all_world(max_pairs=2)
    mock = w.env.mock
    with w.factory() as s:
        assert w.runtime._active_pairs(s) == ("AAAIDR", "BTCIDR")
        for _ in range(8):
            mock.inject_error("GET", "/api/summaries", 500, -1001, "down")
        mock.advance(400_000)  # refresh due, exchange down, list is 400 s old: kept
        assert w.runtime._active_pairs(s) == ("AAAIDR", "BTCIDR")
        mock.advance(600_000)  # 1000 s old, still down: dropped, never trade a stale list
        for _ in range(8):
            mock.inject_error("GET", "/api/summaries", 500, -1001, "down")
        assert w.runtime._active_pairs(s) == ()


def test_candle_refreshes_per_cycle_are_bounded_and_rotate(monkeypatch) -> None:
    from aidss_trader.runtime import loop as loop_module

    w = World("PAPER")
    pairs = tuple(f"P{i:02d}IDR" for i in range(20))
    with w.factory() as s:
        set_allowlist(s, Allowlist(pairs, LIQ), by="owner")
        s.commit()
    seen: list[str] = []
    monkeypatch.setattr(w.runtime, "_refresh_candles", lambda s, pair: seen.append(pair))
    report = loop_module.CycleReport()
    with w.factory() as s:
        w.runtime._candle_poll_s = 300
        w.runtime._refresh_all_candles(s, report)
        assert len(seen) == loop_module.CANDLE_REFRESH_PER_CYCLE
        w.runtime._refresh_all_candles(s, report)
        assert len(seen) == 2 * loop_module.CANDLE_REFRESH_PER_CYCLE
        w.runtime._refresh_all_candles(s, report)
        assert sorted(set(seen)) == sorted(pairs)  # the third call reached the rest
        assert len(seen) == 20  # nothing was refreshed twice inside the poll interval
