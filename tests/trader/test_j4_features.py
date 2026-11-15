"""Jalur 4 tests: backtest persistence, promotion thresholds, and origin-separated portfolio."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from aidss_trader.backtest import (
    BacktestConfig,
    latest_backtest_return_pct,
    record_backtest,
    run_backtest,
)
from aidss_trader.config import RiskLimits
from aidss_trader.connector.types import Candle
from aidss_trader.db.models import (
    AuditLog,
    EquitySnapshot,
    Fill,
    OrderIntentRow,
    OrderRow,
    PaperEquitySnapshot,
)
from aidss_trader.market_data.pairs import PairRules
from aidss_trader.paper import CostModel, PaperConfig
from aidss_trader.promotion import Promotion, SuppliedEvidence, Thresholds
from aidss_trader.runtime.settings_store import get_promotion_thresholds, thresholds_loosen
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy
from tests.trader.test_t5_operator_surface import T0, Api, Clock, paper_sells

D = Decimal


def _candles(count: int = 80) -> list[Candle]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Candle] = []
    price = D("1000000000")
    for i in range(count):
        step = D(i * 2000000)
        close = price + step
        out.append(
            Candle(
                open_time=base + timedelta(hours=4 * i),
                open=close - D("1000000"),
                high=close + D("5000000"),
                low=close - D("5000000"),
                close=close,
                volume=D("10"),
            )
        )
    return out


def _bt_config(ema_fast: int = 5) -> BacktestConfig:
    strategy = EmaAdxStrategy(
        EmaAdxParams(
            ema_fast=ema_fast,
            ema_slow=12,
            adx_period=5,
            adx_threshold=D("10"),
            atr_period=5,
            atr_stop_multiple=D("2"),
            cooldown_s=0,
        )
    )
    limits = RiskLimits(
        risk_per_trade_pct=D("1"),
        max_daily_loss_idr=D("10000000"),
        max_drawdown_pct=D("25"),
        max_consecutive_losses=5,
        max_open_positions=2,
        max_exposure_per_pair_pct=D("50"),
        max_total_exposure_pct=D("80"),
        max_order_idr=D("50000000"),
        price_deviation_pct=D("5"),
        freshness_limit_s=60,
        cooldown_s=0,
        order_rate_limit=10,
    )
    rules = PairRules(
        pair="BTCIDR",
        ticker_id="btc_idr",
        quantity_increment=D("0.00000001"),
        price_increment=D("1000"),
        min_base_idr=D("50000"),
        min_traded_qty=D("0.0001"),
        maintenance=False,
        suspended=False,
        blocked_reasons=(),
    )
    paper = PaperConfig(
        slippage_pct=D("0.1"),
        partial_fill_fraction=D("1"),
        costs=CostModel(D("0.1"), D("0.2"), D("0.1"), D("0.05")),
    )
    return BacktestConfig(
        strategy=strategy,
        limits=limits,
        rules=rules,
        paper=paper,
        start_equity_idr=D("100000000"),
        pair="BTCIDR",
    )


def test_record_backtest_persists_evidence_and_feeds_promotion_gate(session) -> None:
    clock = Clock()
    cfg = _bt_config()
    res = run_backtest(_candles(), cfg)
    version = cfg.strategy.version_id()

    promo = Promotion(session, now=clock)
    promo.register("ema_adx", version)
    clock.advance(weeks=5)
    paper_sells(session, 5, clock.t - timedelta(days=1))

    thresholds = Thresholds(
        min_paper_trades=3,
        max_paper_drawdown_pct=D("20"),
        backtest_min_return_pct=D("-10"),
    )

    gates_before = promo.gates(
        "ema_adx",
        "APPROVAL",
        thresholds,
        SuppliedEvidence(paper_drawdown_pct=D("2")),
    )
    bt_gate_before = next(g for g in gates_before if g.name == "backtest")
    assert not bt_gate_before.passed and bt_gate_before.reason == "no evidence"

    row = record_backtest(session, res, cfg, by="owner", now=clock.t)
    assert row.origin == "BACKTEST"
    assert row.strategy_version == version
    assert latest_backtest_return_pct(session, "ema_adx", version) == row.total_return_pct
    assert any(a.action == "backtest.recorded" for a in session.scalars(select(AuditLog)))

    gates_after = promo.gates(
        "ema_adx",
        "APPROVAL",
        thresholds,
        SuppliedEvidence(paper_drawdown_pct=D("2")),
    )
    bt_gate_after = next(g for g in gates_after if g.name == "backtest")
    assert bt_gate_after.passed and bt_gate_after.measured == str(row.total_return_pct)

    promo.register("ema_adx", "new-version-v2")
    clock.advance(weeks=5)
    gates_v2 = promo.gates(
        "ema_adx",
        "APPROVAL",
        thresholds,
        SuppliedEvidence(paper_drawdown_pct=D("2")),
    )
    bt_gate_v2 = next(g for g in gates_v2 if g.name == "backtest")
    assert not bt_gate_v2.passed and bt_gate_v2.reason == "no evidence"


def test_promotion_thresholds_storage_loosening_and_api() -> None:
    api = Api()
    with api.factory() as s:
        assert get_promotion_thresholds(s) == Thresholds()

    r0 = api.call("GET", "/promotion-thresholds")
    assert r0.status_code == 200
    assert len(r0.json()["data"]["unset"]) == 5

    body_initial = {
        "min_paper_trades": 5,
        "max_paper_drawdown_pct": "15",
        "backtest_min_return_pct": "5",
        "max_live_capital_idr": "25000000",
        "max_slippage_pct": "0.5",
    }
    assert api.call("PUT", "/promotion-thresholds", body=body_initial).status_code == 403
    grant1 = api.grant("RAISE_LIMIT")
    r_save = api.call("PUT", "/promotion-thresholds", body=body_initial, step_up=grant1)
    assert r_save.status_code == 200
    assert r_save.json()["data"]["unset"] == []

    body_tighter = {
        "min_paper_trades": 10,
        "max_paper_drawdown_pct": "10",
        "backtest_min_return_pct": "8",
        "max_live_capital_idr": "20000000",
        "max_slippage_pct": "0.3",
    }
    r_tight = api.call("PUT", "/promotion-thresholds", body=body_tighter)
    assert r_tight.status_code == 200
    assert r_tight.json()["data"]["thresholds"]["min_paper_trades"] == 10

    body_looser = {**body_tighter, "max_paper_drawdown_pct": "12"}
    assert api.call("PUT", "/promotion-thresholds", body=body_looser).status_code == 403
    grant2 = api.grant("RAISE_LIMIT")
    r_loose = api.call("PUT", "/promotion-thresholds", body=body_looser, step_up=grant2)
    assert r_loose.status_code == 200

    body_unset = {**body_looser, "max_slippage_pct": None}
    r_unset = api.call("PUT", "/promotion-thresholds", body=body_unset)
    assert r_unset.status_code == 200
    assert r_unset.json()["data"]["unset"] == ["max_slippage_pct"]


def test_portfolio_endpoint_strictly_separates_live_paper_and_backtest_origins() -> None:
    api = Api()
    with api.factory() as s:
        live_order = OrderRow(
            origin="LIVE",
            pair="BTCIDR",
            side="BUY",
            type="LIMIT",
            price=D("1000000000"),
            quantity=D("0.01"),
            executed_qty=D("0.01"),
            client_order_id="c-live-1",
            state="FILLED",
            purpose="ENTRY",
            submitted_at=T0,
            updated_at=T0,
        )
        paper_order = OrderRow(
            origin="PAPER",
            pair="ETHIDR",
            side="BUY",
            type="LIMIT",
            price=D("40000000"),
            quantity=D("0.5"),
            executed_qty=D("0.5"),
            client_order_id="c-paper-1",
            state="FILLED",
            purpose="ENTRY",
            submitted_at=T0,
            updated_at=T0,
        )
        s.add_all([live_order, paper_order])
        s.flush()
        s.add_all(
            [
                Fill(
                    order_id=live_order.id,
                    origin="LIVE",
                    exchange_trade_id="t-live-1",
                    pair="BTCIDR",
                    side="BUY",
                    price=D("1000000000"),
                    quantity=D("0.01"),
                    quote_quantity=D("10000000"),
                    commission=D("10000"),
                    executed_at=T0,
                ),
                Fill(
                    order_id=paper_order.id,
                    origin="PAPER",
                    exchange_trade_id="t-paper-1",
                    pair="ETHIDR",
                    side="BUY",
                    price=D("40000000"),
                    quantity=D("0.5"),
                    quote_quantity=D("20000000"),
                    commission=D("20000"),
                    executed_at=T0,
                ),
                OrderIntentRow(
                    identity="v1|BTCIDR|1|BUY",
                    origin="LIVE",
                    strategy_version="v1",
                    pair="BTCIDR",
                    side="BUY",
                    entry_price=D("1000000000"),
                    quantity=D("0.01"),
                    stop_price=D("950000000"),
                    risk_amount_idr=D("500000"),
                    rule_snapshot={"target_price": "1100000000"},
                    state="SUBMITTED",
                    created_at=T0,
                ),
                EquitySnapshot(at=T0, equity_idr=D("100000000")),
                PaperEquitySnapshot(at=T0, equity_idr=D("50000000")),
            ]
        )
        cfg = _bt_config()
        res = run_backtest(_candles(), cfg)
        record_backtest(s, res, cfg, by="owner", now=T0)
        s.commit()

    resp = api.call("GET", "/portfolio")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["live"]["origin"] == "LIVE"
    assert data["paper"]["origin"] == "PAPER"
    assert len(data["live"]["positions"]) == 1
    assert data["live"]["positions"][0]["pair"] == "BTCIDR"
    assert data["live"]["positions"][0]["origin"] == "LIVE"
    assert data["live"]["positions"][0]["stop_price"] == "950000000"
    assert data["live"]["positions"][0]["target_price"] == "1100000000"
    assert data["live"]["latest_equity_idr"] == "100000000"

    assert len(data["paper"]["positions"]) == 1
    assert data["paper"]["positions"][0]["pair"] == "ETHIDR"
    assert data["paper"]["positions"][0]["origin"] == "PAPER"
    assert data["paper"]["latest_equity_idr"] == "50000000"

    assert len(data["backtests"]) == 1
    assert data["backtests"][0]["origin"] == "BACKTEST"
    assert data["backtests"][0]["pair"] == "BTCIDR"


def test_thresholds_loosen_helper() -> None:
    a = Thresholds(min_paper_trades=10, max_paper_drawdown_pct=D("10"))
    assert not thresholds_loosen(a, Thresholds(min_paper_trades=12, max_paper_drawdown_pct=D("8")))
    assert thresholds_loosen(a, Thresholds(min_paper_trades=8, max_paper_drawdown_pct=D("10")))
    assert thresholds_loosen(a, Thresholds(min_paper_trades=10, max_paper_drawdown_pct=D("12")))
    unset_trades = Thresholds(min_paper_trades=None, max_paper_drawdown_pct=D("10"))
    assert not thresholds_loosen(a, unset_trades)
