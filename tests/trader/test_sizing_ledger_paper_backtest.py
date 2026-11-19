from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidss_trader.backtest import BacktestConfig, run_backtest
from aidss_trader.config.limits import RiskLimits
from aidss_trader.connector.types import BookTicker, Candle, PairInfo
from aidss_trader.intents import (
    build_entry_intent,
    build_exit_intent,
    client_order_id,
    intent_identity,
)
from aidss_trader.ledger import LedgerIntegrityError, Position, apply_fill, replay, unrealised
from aidss_trader.market_data import build_pair_rules
from aidss_trader.orders import (
    TERMINAL,
    TRANSITIONS,
    IllegalTransition,
    OrderState,
    can_transition,
    from_exchange,
)
from aidss_trader.paper import CostModel, PaperConfig, PaperExecutor, PaperRejected
from aidss_trader.strategy import EmaAdxParams, EmaAdxStrategy, Signal, SignalKind

D = Decimal
T0 = datetime(2026, 1, 1, tzinfo=UTC)

# Every number below is a TEST value defined here. None is a default and none is the owner's.
LIMITS = RiskLimits(
    risk_per_trade_pct=D("1"),
    max_daily_loss_idr=D("1000000"),
    max_drawdown_pct=D("20"),
    max_consecutive_losses=3,
    max_open_positions=2,
    max_exposure_per_pair_pct=D("50"),
    max_total_exposure_pct=D("80"),
    max_order_idr=D("50000000"),
    price_deviation_pct=D("2"),
    freshness_limit_s=60,
    cooldown_s=0,
    order_rate_limit=5,
)
COSTS = CostModel(D("0.1"), D("0.2"), D("0.1"), D("0.01"))
PAPER = PaperConfig(slippage_pct=D("0.1"), partial_fill_fraction=D("1"), costs=COSTS)
PARAMS = EmaAdxParams(3, 6, 3, D("30"), 3, D("2"), 0)


def pair_info(**kw) -> PairInfo:
    base = dict(
        pair="BTCIDR",
        ticker_id="btc_idr",
        base_asset="IDR",
        quote_asset="BTC",
        quantity_increment=D("0.00000001"),
        min_base_idr=D("50000"),
        min_traded_qty=D("0.0001"),
        maintenance=False,
        suspended=False,
        maker_fee_pct=None,
        taker_fee_pct=None,
        raw={"pricescale": 1000},
    )
    base.update(kw)
    return PairInfo(**base)


RULES = build_pair_rules([pair_info()], {"btc_idr": D("1000")})["BTCIDR"]
ENTRY = Signal(SignalKind.ENTRY, "x", stop_hint=D("1180000000"), inputs={"adx": "50"})


def build(**kw):
    args = dict(
        strategy_version="v1",
        pair="BTCIDR",
        candle_open=T0,
        equity_idr=D("100000000"),
        limits=LIMITS,
        rules=RULES,
        best_bid=D("1236777000"),
        mode="PAPER",
    )
    args.update(kw)
    return build_entry_intent(ENTRY, **args)


# ------------------------------------------------------------------- sizing


def test_entry_is_sized_from_the_stop_and_rounded_down() -> None:
    r = build()
    i = r.intent
    assert i is not None and i.entry_price == D("1236777000") and i.side == "BUY"
    risk_cap = D("100000000") * D("1") / 100
    assert i.risk_amount_idr <= risk_cap  # rounding down: realised risk never exceeds the budget
    assert i.quantity == i.quantity.quantize(D("0.00000001"))


def test_no_stop_or_a_stop_above_entry_is_refused() -> None:
    for stop in (None, D("1236777000"), D("1300000000")):
        r = build_entry_intent(
            Signal(SignalKind.ENTRY, "x", stop_hint=stop),
            strategy_version="v",
            pair="BTCIDR",
            candle_open=T0,
            equity_idr=D("100000000"),
            limits=LIMITS,
            rules=RULES,
            best_bid=D("1236777000"),
            mode="PAPER",
        )
        assert r.intent is None and "stop" in r.reasons[0]


def test_an_unset_limit_refuses_the_intent_and_names_it() -> None:
    from dataclasses import replace

    r = build(limits=replace(LIMITS, max_order_idr=None))
    assert r.intent is None and "limit unset: max_order_idr" in r.reasons
    assert build(limits=None).intent is None


def test_the_order_value_cap_clamps_the_quantity() -> None:
    from dataclasses import replace

    capped = build(limits=replace(LIMITS, max_order_idr=D("2000000"))).intent
    assert capped.quantity * capped.entry_price <= D("2000000")


def test_below_the_pair_minimum_creates_no_intent() -> None:
    r = build(equity_idr=D("1000"))
    assert r.intent is None


def test_a_blocked_pair_creates_no_intent() -> None:
    blocked = build_pair_rules([pair_info(suspended=True)], {"btc_idr": D("1000")})["BTCIDR"]
    assert build(rules=blocked).intent is None


def test_identity_and_client_order_id_are_pure_and_valid() -> None:
    import re

    a, b = intent_identity("v1", "BTCIDR", T0, "BUY"), intent_identity("v1", "BTCIDR", T0, "BUY")
    assert a == b and a != intent_identity("v1", "BTCIDR", T0 + timedelta(hours=4), "BUY")
    cid = client_order_id(a)
    assert cid == client_order_id(a) and re.fullmatch(r"[A-Za-z0-9_-]{1,36}", cid)
    assert client_order_id(a, 1) != cid  # a reprice is a new order
    assert build().intent.identity == build().intent.identity


def test_a_signal_exit_is_a_limit_sell_at_the_best_ask_and_dust_is_reported() -> None:
    exit_sig = Signal(SignalKind.EXIT, "trend_filter_failed")
    ok = build_exit_intent(
        exit_sig,
        strategy_version="v",
        pair="BTCIDR",
        candle_open=T0,
        position_qty=D("0.002"),
        rules=RULES,
        best_ask=D("1236800000"),
        mode="PAPER",
    )
    assert ok.intent.side == "SELL" and ok.intent.entry_price == D("1236800000")
    dust = build_exit_intent(
        exit_sig,
        strategy_version="v",
        pair="BTCIDR",
        candle_open=T0,
        position_qty=D("0.00001"),
        rules=RULES,
        best_ask=D("1236800000"),
        mode="PAPER",
    )
    assert dust.intent is None and dust.reasons


# ------------------------------------------------------------- state machine


def test_every_listed_transition_is_allowed_and_terminal_states_have_none() -> None:
    for state, targets in TRANSITIONS.items():
        for target in targets:
            assert can_transition(state, target)
    for terminal in TERMINAL:
        assert TRANSITIONS[terminal] == frozenset()
    assert not can_transition(OrderState.FILLED, OrderState.OPEN)
    assert not can_transition(OrderState.OPEN, OrderState.SUBMITTING)


def test_unknown_resolves_to_any_real_outcome_and_is_never_terminal() -> None:
    assert OrderState.UNKNOWN not in TERMINAL
    for outcome in (OrderState.OPEN, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED):
        assert can_transition(OrderState.UNKNOWN, outcome)


def test_exchange_statuses_map_and_an_unknown_one_is_an_error() -> None:
    assert from_exchange("NEW") is OrderState.OPEN and from_exchange("FILLED") is OrderState.FILLED
    with pytest.raises(IllegalTransition):
        from_exchange("FILL")  # the WebSocket spelling (docs/06-INTEGRATIONS/11, D5)


# ---------------------------------------------------------- ledger and paper


def test_weighted_average_cost_and_realised_pnl_net_of_costs() -> None:
    pos, realised = apply_fill(Position(), "BUY", D("2"), D("100"), D("2"))
    assert pos == Position(D("2"), D("101")) and realised == 0
    pos, realised = apply_fill(pos, "BUY", D("2"), D("120"), D("2"))
    assert pos.quantity == 4 and pos.avg_cost == D("111")  # (2*101 + 2*120 + 2) / 4
    pos, realised = apply_fill(pos, "SELL", D("1"), D("130"), D("1"))
    assert realised == D("18") and pos.avg_cost == D("111")  # (130-111)*1 - 1
    assert unrealised(pos, D("120")) == D("27")


def test_a_sell_larger_than_the_position_is_an_integrity_error() -> None:
    with pytest.raises(LedgerIntegrityError):
        apply_fill(Position(D("1"), D("10")), "SELL", D("2"), D("10"), D("0"))
    with pytest.raises(LedgerIntegrityError):
        apply_fill(Position(), "BUY", D("0"), D("10"), D("0"))


def test_replay_totals_realised_pnl() -> None:
    pos, total = replay([("BUY", D("2"), D("100"), D("0")), ("SELL", D("2"), D("110"), D("0"))])
    assert pos == Position() and total == D("20")


def cndl(open_, high, low, close) -> Candle:
    return Candle(T0, D(open_), D(high), D(low), D(close), D(1))


def test_a_paper_limit_buy_fills_only_if_price_trades_through() -> None:
    ex = PaperExecutor(PAPER)
    assert (
        ex.limit_against_candle("BUY", D("100"), D("1"), cndl(105, 110, 100, 108)) is None
    )  # touch
    fill = ex.limit_against_candle("BUY", D("100"), D("1"), cndl(105, 110, 99, 108))
    assert fill.price == D("100") and fill.maker and fill.cost > 0
    assert ex.limit_against_candle("SELL", D("110"), D("1"), cndl(105, 110, 100, 108)) is None
    assert ex.limit_against_candle("SELL", D("110"), D("1"), cndl(105, 111, 100, 108)) is not None


def test_paper_partial_fills_use_the_configured_fraction() -> None:
    half = PaperExecutor(PaperConfig(D("0.1"), D("0.5"), COSTS))
    assert half.limit_against_candle(
        "BUY", D("100"), D("2"), cndl(105, 110, 99, 108)
    ).quantity == D("1")


def test_paper_market_fills_move_against_the_trader_and_pay_taker_costs() -> None:
    ex = PaperExecutor(PAPER)
    assert ex.market("BUY", D("1"), D("1000")).price == D("1001")
    sell = ex.market("SELL", D("1"), D("1000"))
    assert sell.price == D("999") and not sell.maker


def test_paper_moc_that_would_cross_is_rejected() -> None:
    book = BookTicker("BTCIDR", D("99"), D("1"), D("100"), D("1"))
    ex = PaperExecutor(PAPER)
    with pytest.raises(PaperRejected):
        ex.check_moc("BUY", D("100"), book)
    ex.check_moc("BUY", D("99"), book)  # resting at the bid is fine


def test_paper_config_is_validated_and_has_no_defaults() -> None:
    with pytest.raises(TypeError):
        PaperConfig()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PaperConfig(D("0.1"), D("0"), COSTS)


# ------------------------------------------------------------------ backtest


def trending(n_up: int = 30, n_down: int = 25) -> list[Candle]:
    closes = [1_200_000_000 + 4_000_000 * i for i in range(n_up)]
    top = closes[-1]
    closes += [top - 6_000_000 * i for i in range(1, n_down + 1)]
    out = []
    for i, c in enumerate(closes):
        out.append(
            Candle(
                T0 + timedelta(hours=4 * i), D(c), D(c + 2_000_000), D(c - 2_000_000), D(c), D(1)
            )
        )
    return out


def config(**kw) -> BacktestConfig:
    base = dict(
        strategy=EmaAdxStrategy(PARAMS),
        limits=LIMITS,
        rules=RULES,
        paper=PAPER,
        start_equity_idr=D("100000000"),
        pair="BTCIDR",
    )
    base.update(kw)
    return BacktestConfig(**base)


def test_backtest_has_no_lookahead() -> None:
    seen: list[tuple[int, int]] = []
    run_backtest(trending(), config(), on_decision=lambda i, n: seen.append((i, n)))
    assert seen and all(n == i + 1 for i, n in seen)  # history is exactly candles[:i+1]


def test_backtest_is_reproducible_and_labelled_as_a_backtest() -> None:
    a, b = run_backtest(trending(), config()), run_backtest(trending(), config())
    assert a.data_fingerprint == b.data_fingerprint and a.final_equity == b.final_equity
    assert a.origin == "BACKTEST"
    changed = run_backtest(trending(), config(start_equity_idr=D("200000000")))
    assert changed.data_fingerprint != a.data_fingerprint


def test_a_trend_then_reversal_produces_a_closed_trade_with_costs_applied() -> None:
    r = run_backtest(trending(), config())
    assert r.trades, "the strategy should have entered and exited"
    t = r.trades[0]
    gross = (t.exit_price - t.entry_price) * t.quantity
    assert t.pnl_net < gross  # costs and slippage always reduce the result
    assert r.metrics["trades"] == len(r.trades)
    assert r.final_equity != config().start_equity_idr


def test_the_equity_curve_has_one_point_per_candle() -> None:
    candles = trending()
    assert len(run_backtest(candles, config()).equity_curve) == len(candles)


def test_a_gap_down_through_the_stop_exits_at_the_gap_not_at_the_stop() -> None:
    candles = trending(n_up=30, n_down=0)
    top = candles[-1].close
    crash = top - 100_000_000
    candles.append(
        Candle(T0 + timedelta(hours=4 * 30), D(crash), D(crash + 1), D(crash - 1), D(crash), D(1))
    )
    candles.append(
        Candle(T0 + timedelta(hours=4 * 31), D(crash), D(crash + 1), D(crash - 1), D(crash), D(1))
    )
    r = run_backtest(candles, config())
    stopped = [t for t in r.trades if t.exit_reason.startswith("stop")]
    assert stopped and stopped[0].exit_price < top - 50_000_000  # far below any sane stop level


def test_backtest_needs_every_cost_so_it_cannot_run_on_a_guess() -> None:
    with pytest.raises(TypeError):
        CostModel(D("0.1"), D("0.2"))  # type: ignore[call-arg]


def test_the_tax_is_charged_on_a_sale_only_as_indodax_does() -> None:
    """Read from the owner's account screen (IDR market): buy = service fee + bourse fee, tax 0%;
    sell = service fee + 0.21% tax + bourse fee. The model first charged the tax on both sides."""
    costs = CostModel(D("0.1"), D("0.2"), D("0.21"), D("0.00555"))
    value = D("1000000")
    assert costs.cost(value, maker=True, side="BUY") == value * D("0.10555") / 100
    assert costs.cost(value, maker=False, side="BUY") == value * D("0.20555") / 100
    assert costs.cost(value, maker=True, side="SELL") == value * D("0.31555") / 100
    assert costs.cost(value, maker=False, side="SELL") == value * D("0.41555") / 100


def test_a_round_trip_pays_the_tax_once() -> None:
    costs = CostModel(D("0.1"), D("0.2"), D("0.21"), D("0.00555"))
    value = D("100000")
    round_trip = costs.cost(value, maker=True, side="BUY") + costs.cost(
        value, maker=True, side="SELL"
    )
    assert round_trip == value * D("0.42110") / 100  # 0.10555 + 0.31555, not 0.10555 + 0.52555


def test_a_cost_needs_a_known_side() -> None:
    import pytest

    with pytest.raises(ValueError):
        CostModel(D("0.1"), D("0.2"), D("0.21"), D("0.005")).cost(D("1"), maker=True, side="HOLD")
