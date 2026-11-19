"""Several strategies in the paper book, one owner per pair (S2, ADR-062).

Test values only: no exchange, no real number of the owner's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import Base
from aidss_trader.db.models import Fill, OrderIntentRow, OrderRow
from aidss_trader.promotion import Promotion
from aidss_trader.risk.engine import evaluate
from aidss_trader.runtime.ownership import (
    OwnershipError,
    paper_entry_refusal,
    paper_ownership,
    strategy_stats,
)
from aidss_trader.runtime.settings_store import (
    StrategyDef,
    set_strategy_def,
    set_strategy_enabled,
)
from aidss_trader.strategy.kinds import build_strategy
from tests.trader.test_runtime_wiring import LIMITS as WORLD_LIMITS
from tests.trader.test_runtime_wiring import World, api_for, warm
from tests.trader.test_t4_risk_orders_safety import LIMITS as RISK_LIMITS
from tests.trader.test_t4_risk_orders_safety import ctx as risk_ctx
from tests.trader.test_t4_risk_orders_safety import intent as risk_intent

T0 = datetime(2026, 5, 1, tzinfo=UTC)
DONCHIAN = {
    "entry_period": "20",
    "exit_period": "10",
    "atr_period": "3",
    "atr_stop_multiple": "2",
    "cooldown_s": "0",
}


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    ).execution_options(schema_translate_map={"trading": None})
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        yield s


_n = [0]


def _leg(session, pair, side, price, at, intent, qty=D("1")):
    _n[0] += 1
    order = OrderRow(
        intent_identity=intent,
        origin="PAPER",
        pair=pair,
        side=side,
        type="LIMIT",
        quantity=qty,
        client_order_id=f"t{_n[0]}",
        executed_qty=qty,
        state="FILLED",
        purpose="ENTRY" if side == "BUY" else "EXIT",
        submitted_at=at,
        updated_at=at,
    )
    session.add(order)
    session.flush()
    session.add(
        Fill(
            order_id=order.id,
            origin="PAPER",
            exchange_trade_id=f"x{_n[0]}",
            pair=pair,
            side=side,
            price=price,
            quantity=qty,
            quote_quantity=price * qty,
            executed_at=at,
        )
    )


def _intent(session, strategy_id, pair, at, state="PAPER_FILLED", side="BUY"):
    identity = f"{strategy_id or 'ema_adx'}-v|{pair}|{at.isoformat()}|{side}"
    session.add(
        OrderIntentRow(
            identity=identity,
            origin="PAPER",
            strategy_version=f"{strategy_id or 'ema_adx'}-v",
            strategy_id=strategy_id,
            pair=pair,
            side=side,
            entry_price=D("100"),
            quantity=D("1"),
            state=state,
            created_at=at,
        )
    )
    return identity


def open_position(session, strategy_id, pair, at, price=D("100")):
    identity = _intent(session, strategy_id, pair, at)
    _leg(session, pair, "BUY", price, at, identity)
    session.commit()


def close_position(session, pair, price, at):
    _leg(session, pair, "SELL", price, at, None)  # a stop or an exit with no intent of its own
    session.commit()


# -------------------------------------------------------------------- ownership


def test_a_pair_is_free_owned_then_free_again(session) -> None:
    assert paper_ownership(session).owner_of("AAAIDR") is None
    open_position(session, "dc", "AAAIDR", T0)
    own = paper_ownership(session)
    assert own.owners == {"AAAIDR": "dc"} and own.blocked_for("AAAIDR", "dc") is None
    assert own.blocked_for("AAAIDR", "rsi") == "pair_owned_by:dc"
    assert own.blocked_for("BBBIDR", "rsi") is None
    close_position(session, "AAAIDR", D("110"), T0 + timedelta(hours=4))
    again = paper_ownership(session)
    assert again.owners == {} and again.blocked_for("AAAIDR", "rsi") is None


def test_an_old_intent_without_a_strategy_belongs_to_the_reference(session) -> None:
    open_position(session, None, "AAAIDR", T0)
    assert paper_ownership(session).owners == {"AAAIDR": "ema_adx"}


def test_a_waiting_entry_claims_the_pair_until_it_ends(session) -> None:
    _intent(session, "dc", "AAAIDR", T0, state="PAPER_RECORDED")
    session.commit()
    own = paper_ownership(session)
    assert own.claims == {"AAAIDR": "dc"} and own.blocked_for("AAAIDR", "rsi") == "pair_owned_by:dc"
    session.scalar(select(OrderIntentRow)).state = "PAPER_UNFILLED"
    session.commit()
    assert paper_ownership(session).blocked_for("AAAIDR", "rsi") is None


def test_two_claims_on_one_pair_block_it_for_everyone(session) -> None:
    _intent(session, "dc", "AAAIDR", T0, state="PAPER_RECORDED")
    _intent(session, "rsi", "AAAIDR", T0 + timedelta(seconds=1), state="PAPER_RECORDED")
    session.commit()
    own = paper_ownership(session)
    assert own.blocked_for("AAAIDR", "dc") == "pair_ownership_conflict"
    assert own.blocked_for("AAAIDR", "rsi") == "pair_ownership_conflict"


def test_a_sale_goes_to_the_strategy_that_opened_the_position(session) -> None:
    open_position(session, "dc", "AAAIDR", T0)
    close_position(session, "AAAIDR", D("90"), T0 + timedelta(hours=4))  # a stop: no intent
    open_position(session, "rsi", "AAAIDR", T0 + timedelta(hours=8))
    close_position(session, "AAAIDR", D("120"), T0 + timedelta(hours=12))
    own = paper_ownership(session)
    assert [(t.strategy_id, t.realised) for t in own.trades] == [("dc", D("-10")), ("rsi", D("20"))]
    assert own.last_exit("dc", "AAAIDR") == T0 + timedelta(hours=4)
    assert own.last_exit("rsi", "BBBIDR") is None


def test_stats_are_each_strategys_own_and_drawdown_is_not_the_accounts(session) -> None:
    for i, (sid, exit_price) in enumerate([("a", D("120")), ("b", D("50")), ("a", D("60"))]):
        at = T0 + timedelta(days=i)
        open_position(session, sid, f"P{i}IDR", at)
        close_position(session, f"P{i}IDR", exit_price, at + timedelta(hours=4))
    stats = strategy_stats(paper_ownership(session), D("1000"))
    assert (stats["a"].trades, stats["a"].wins, stats["a"].pnl) == (2, 1, D("-20"))
    assert stats["b"].trades == 1 and stats["b"].wins == 0
    # a: +20 then -40 on 1000: equity 1020 then 980, the fall from the 1020 peak
    assert round(stats["a"].drawdown_pct, 4) == round(D("40") / D("1020") * 100, 4)
    assert "c" not in stats  # no trade, no evidence: never a zero


def test_a_buy_with_no_intent_is_refused_not_guessed(session) -> None:
    _leg(session, "AAAIDR", "BUY", D("100"), T0, None)
    session.commit()
    with pytest.raises(OwnershipError):
        paper_ownership(session)


def test_an_impossible_sale_is_an_ownership_error(session) -> None:
    close_position(session, "AAAIDR", D("100"), T0)
    with pytest.raises(OwnershipError):
        paper_ownership(session)


# ------------------------------------------------------------- shared limits


@pytest.mark.parametrize("open_positions", [0, 1, 2, 3])
@pytest.mark.parametrize("pair_exposure", [D("0"), D("30000000"), D("49000000")])
@pytest.mark.parametrize("total_exposure", [D("0"), D("60000000"), D("79000000")])
def test_the_paper_limits_agree_with_the_risk_engine(
    open_positions, pair_exposure, total_exposure
) -> None:
    intent = risk_intent(quantity=D("0.01"))
    value = intent.quantity * intent.entry_price
    live = evaluate(
        intent,
        risk_ctx(
            open_positions=open_positions,
            pair_exposure_idr=pair_exposure,
            total_exposure_idr=total_exposure,
        ),
        "ENTRY",
    )
    portfolio = {"open_positions", "pair_exposure", "total_exposure"}
    live_ok = all(c.passed for c in live.checks if c.name in portfolio)
    paper = paper_entry_refusal(
        limits=RISK_LIMITS,
        equity=D("100000000"),
        open_positions=open_positions,
        pair_exposure=pair_exposure,
        total_exposure=total_exposure,
        value=value,
    )
    assert (paper is None) == live_ok


def test_paper_refuses_when_a_limit_is_unset_or_there_is_no_equity() -> None:
    from dataclasses import replace

    kw = dict(
        equity=D("100000000"),
        open_positions=0,
        pair_exposure=D("0"),
        total_exposure=D("0"),
        value=D("1000"),
    )
    assert paper_entry_refusal(limits=replace(RISK_LIMITS, max_open_positions=None), **kw)
    assert paper_entry_refusal(limits=RISK_LIMITS, **{**kw, "equity": D("0")})


# ------------------------------------------------------------- the paper loop


def _define(w: World, sid: str, params=None, enabled=True) -> str:
    with w.factory() as s:
        d = StrategyDef(sid, "donchian_breakout", sid, dict(params or DONCHIAN))
        set_strategy_def(s, d, by="owner")
        version = build_strategy(d.kind, d.params).version_id()
        Promotion(s).register(sid, version)
        if enabled:
            set_strategy_enabled(s, sid, True, by="owner")
        s.commit()
    return version


def test_two_strategies_signalling_the_same_pair_make_exactly_one_intent() -> None:
    w = World("PAPER")
    _define(w, "dc")  # sorts before ema_adx, so it takes the pair
    warm(w)
    buys = [i for i in w.rows(OrderIntentRow) if i.side == "BUY"]
    assert [(i.strategy_id, i.pair) for i in buys] == [("dc", "BTCIDR")]
    assert w.posts() == 0


def test_the_lower_id_wins_and_the_loser_is_told_why() -> None:
    w = World("PAPER")
    _define(w, "zz")  # sorts after ema_adx
    first = w.cycle()
    second = w.cycle()
    reasons = [x for r in (first, second) for x in r.skipped]
    buys = [i for i in w.rows(OrderIntentRow) if i.side == "BUY"]
    assert {i.strategy_id for i in buys} == {"ema_adx"}
    assert any("zz: pair_owned_by:ema_adx" in x for x in reasons)


def test_extra_strategies_never_reach_the_live_book() -> None:
    w = World("PAPER")
    _define(w, "dc")
    for _ in range(6):
        w.cycle()
    assert w.rows(OrderIntentRow)
    assert all(i.origin == "PAPER" for i in w.rows(OrderIntentRow))
    assert all(o.origin == "PAPER" for o in w.rows(OrderRow))
    assert all(f.origin == "PAPER" for f in w.rows(Fill))
    assert w.posts() == 0  # nothing was ever sent to the exchange


def test_a_disabled_strategy_makes_no_intent() -> None:
    w = World("PAPER")
    _define(w, "dc", enabled=False)
    warm(w)
    assert {i.strategy_id for i in w.rows(OrderIntentRow)} == {"ema_adx"}


def test_an_unregistered_version_is_skipped_not_guessed() -> None:
    w = World("PAPER")
    _define(w, "dc")
    with w.factory() as s:
        s.get(
            __import__("aidss_trader.db.models", fromlist=["StrategyRow"]).StrategyRow, "dc"
        ).version = "old"
        s.commit()
    report = warm(w)
    assert any("dc: version is not registered as PAPER" in x for x in report.skipped)
    assert {i.strategy_id for i in w.rows(OrderIntentRow)} == {"ema_adx"}


def test_paper_entries_obey_max_open_positions() -> None:
    from dataclasses import replace

    w = World("PAPER", limits=replace(WORLD_LIMITS, max_open_positions=1))
    # One pair, so a second entry would be refused by ownership anyway; hold the only slot with
    # a position in another pair and the reference's entry must be refused by the limit.
    with w.factory() as s:
        open_position(s, "dc", "OTHERIDR", datetime.now(UTC) - timedelta(days=1))
    # The made-up open position has no price or stop, so the Trader halts after the first cycle;
    # the first cycle is the one that decides.
    report = w.cycle()
    assert not [i for i in w.rows(OrderIntentRow) if i.pair == "BTCIDR"]
    assert any("open_positions" in x for x in report.skipped)


# ------------------------------------------------------------------------ API


def _api():
    w = World("PAPER", configured=True)
    return w, api_for(w)


def _create(call, sid="dc", params=None):
    return call(
        "POST",
        "/strategy-defs",
        {"id": sid, "label": sid, "kind": "donchian_breakout", "params": params or DONCHIAN},
    )


def test_enable_registers_the_strategy_and_disable_stops_it() -> None:
    w, call = _api()
    assert _create(call).status_code == 201
    assert call("PUT", "/strategy-defs/dc/paper", {"enabled": True}).json()["data"]["enabled"]
    listed = {d["id"]: d for d in call("GET", "/strategy-defs").json()["data"]}
    assert listed["dc"]["paper_enabled"] is True
    with w.factory() as s:
        from aidss_trader.db.models import StrategyRow

        assert s.get(StrategyRow, "dc").mode == "PAPER"
    off = call("PUT", "/strategy-defs/dc/paper", {"enabled": False}).json()["data"]
    assert off["enabled"] is False
    assert call("GET", "/strategy-defs/dc/paper").json()["meta"]["origin"] == "PAPER"


def test_the_reference_strategy_is_not_switched_here_and_unknown_ids_are_404() -> None:
    _w, call = _api()
    r = call("PUT", "/strategy-defs/ema_adx/paper", {"enabled": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "reference_has_own_mode"
    assert call("PUT", "/strategy-defs/nope/paper", {"enabled": True}).status_code == 404
    assert call("GET", "/strategy-defs/nope/paper").status_code == 404


def test_at_most_eight_strategies_can_be_enabled() -> None:
    _w, call = _api()
    for i in range(9):
        params = {**DONCHIAN, "entry_period": str(20 + i)}
        assert _create(call, f"s{i}", params).status_code == 201
    for i in range(8):
        assert call("PUT", f"/strategy-defs/s{i}/paper", {"enabled": True}).status_code == 200
    r = call("PUT", "/strategy-defs/s8/paper", {"enabled": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_enabled"
    assert call("PUT", "/strategy-defs/s0/paper", {"enabled": True}).status_code == 200  # no-op


def test_two_definitions_with_the_same_numbers_are_refused() -> None:
    _w, call = _api()
    assert _create(call, "dc").status_code == 201
    r = _create(call, "dc2")
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_parameters"
    assert _create(call, "dc2", {**DONCHIAN, "entry_period": "25"}).status_code == 201
    edit = call("PUT", "/strategy-defs/dc2", {"label": "x", "params": DONCHIAN})
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "duplicate_parameters"
    same = call("PUT", "/strategy-defs/dc", {"label": "renamed", "params": DONCHIAN})
    assert same.status_code == 200  # editing a definition to its own numbers is not a duplicate


def test_a_strategy_built_here_cannot_be_promoted() -> None:
    _w, call = _api()
    _create(call)
    call("PUT", "/strategy-defs/dc/paper", {"enabled": True})
    r = call("POST", "/strategies/dc/promote", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "paper_only"


def test_editing_an_enabled_strategy_keeps_it_registered_as_paper() -> None:
    w, call = _api()
    _create(call)
    call("PUT", "/strategy-defs/dc/paper", {"enabled": True})
    new = call(
        "PUT", "/strategy-defs/dc", {"label": "dc", "params": {**DONCHIAN, "entry_period": "30"}}
    )
    version = new.json()["data"]["version"]
    with w.factory() as s:
        from aidss_trader.db.models import StrategyRow

        row = s.get(StrategyRow, "dc")
        assert row.version == version and row.mode == "PAPER"


def test_a_strategy_holding_a_paper_position_cannot_be_deleted() -> None:
    w, call = _api()
    _create(call)
    with w.factory() as s:
        open_position(s, "dc", "AAAIDR", datetime.now(UTC) - timedelta(hours=1))
    r = call("DELETE", "/strategy-defs/dc")
    assert r.status_code == 409 and r.json()["error"]["code"] == "strategy_in_use"
    with w.factory() as s:
        close_position(s, "AAAIDR", D("100"), datetime.now(UTC))
    assert call("DELETE", "/strategy-defs/dc").status_code == 200


def test_the_paper_figures_are_the_strategys_own_and_labelled_paper() -> None:
    w, call = _api()
    _create(call)
    with w.factory() as s:
        open_position(s, "dc", "AAAIDR", T0)
        close_position(s, "AAAIDR", D("130"), T0 + timedelta(hours=4))
        open_position(s, "other", "BBBIDR", T0)
        close_position(s, "BBBIDR", D("10"), T0 + timedelta(hours=4))
    body = call("GET", "/strategy-defs/dc/paper").json()
    stats = body["data"]["stats"]
    assert body["meta"]["origin"] == "PAPER"
    assert (stats["trades"], stats["wins"], D(stats["pnl_idr"])) == (1, 1, D("30"))
