"""Hermetic tests for the KORO Atlas spot-adapted strategy, indicators, and proposed profile."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aidss_trader.backtest import BacktestConfig, run_backtest
from aidss_trader.config.limits import RiskLimits
from aidss_trader.connector.types import Candle
from aidss_trader.market_data.pairs import PairRules
from aidss_trader.paper.executor import CostModel, PaperConfig
from aidss_trader.strategy.base import PositionState, SignalKind
from aidss_trader.strategy.catalog import proposed_strategies
from aidss_trader.strategy.indicators import lag1_autocorr, obv, obv_slope, variance_ratio
from aidss_trader.strategy.kinds import build_strategy
from aidss_trader.strategy.koro import KoroObvPullback, KoroObvPullbackParams

ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def _make_candles(closes: list[Decimal], *, volumes: list[Decimal] | None = None) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Candle] = []
    for i, c in enumerate(closes):
        vol = volumes[i] if volumes is not None else D("100")
        out.append(
            Candle(
                open_time=start + timedelta(hours=4 * i),
                open=c,
                high=c + D("20"),
                low=c - D("20"),
                close=c,
                volume=vol,
            )
        )
    return out


def test_decimal_obv_and_slope_detect_uptrend_and_downtrend() -> None:
    up = _make_candles([D("1000") + D(i * 10) for i in range(60)])
    series = obv(up)
    assert series[0] == D("0")
    assert series[-1] > 0
    slopes = obv_slope(up, 48)
    assert slopes[46] is None
    assert slopes[-1] is not None and slopes[-1] > 0

    down = _make_candles([D("2000") - D(i * 10) for i in range(60)])
    assert obv_slope(down, 48)[-1] < 0


def test_lag1_autocorr_and_variance_ratio_on_trending_series() -> None:
    # Smoothly accelerating uptrend has positive lag-1 autocorrelation and VR > 1.
    closes = [D("1000") + D(i * i) for i in range(1, 70)]
    rho1 = lag1_autocorr(closes, 60)
    vr = variance_ratio(closes, 60, 6)
    assert rho1 is not None and rho1 > 0
    assert vr is not None and vr > 1


def test_koro_obv_pullback_entry_exit_and_extension_cap() -> None:
    # Build rising candles so OBV slope > 0 and EMA21 rises, then end on a pullback bar
    # touching EMA21 within 0.5 ATR.
    base = [D("1000") + D(i * 5) for i in range(55)]
    candles = _make_candles(base)
    from aidss_trader.strategy.indicators import ema

    ema21_prev = ema([c.close for c in candles], 21)[-1]
    assert ema21_prev is not None
    # Pullback bar: close < prev.close, touches EMA21, within 0.5 ATR (TR=40 -> 0.5 ATR = 20).
    pullback_close = ema21_prev + D("5")
    candles.append(
        Candle(
            open_time=candles[-1].open_time + timedelta(hours=4),
            open=candles[-1].close,
            high=candles[-1].close,
            low=ema21_prev - D("5"),
            close=pullback_close,
            volume=D("50"),
        )
    )
    strat = KoroObvPullback(
        KoroObvPullbackParams(
            obv_reg_period=48,
            ema_period=21,
            max_extension_atr=D("0.5"),
            autocorr_window=0,
            vr_horizon=0,
            atr_period=14,
            atr_stop_multiple=D("2.5"),
            cooldown_s=14400,
        )
    )
    sig = strat.evaluate(candles, PositionState(long=False))
    assert sig.kind is SignalKind.ENTRY
    assert sig.reason == "koro_obv_ema_pullback"
    assert sig.stop_hint is not None and sig.stop_hint < pullback_close

    # Overextended bar far below EMA21 (> 0.5 ATR) must be rejected.
    far_candles = list(candles[:-1]) + [
        Candle(
            open_time=candles[-1].open_time,
            open=candles[-2].close,
            high=candles[-2].close,
            low=ema21_prev - D("200"),
            close=ema21_prev - D("180"),
            volume=D("50"),
        )
    ]
    far_sig = strat.evaluate(far_candles, PositionState(long=False))
    assert far_sig.kind is SignalKind.NONE
    assert far_sig.reason == "overextended_from_ema"

    # When holding and OBV slope turns negative, strategy emits EXIT.
    down = _make_candles([D("2000") - D(i * 10) for i in range(60)])
    exit_sig = strat.evaluate(down, PositionState(long=True))
    assert exit_sig.kind is SignalKind.EXIT
    assert exit_sig.reason == "obv_slope_negative"


def test_koro_registered_in_kinds_catalog_and_runs_in_backtest() -> None:
    assert "koro_obv_pullback" in proposed_strategies()
    strat = build_strategy(
        "koro_obv_pullback",
        {
            "obv_reg_period": "48",
            "ema_period": "21",
            "max_extension_atr": "0.5",
            "autocorr_window": "0",
            "vr_horizon": "0",
            "atr_period": "14",
            "atr_stop_multiple": "2.5",
            "cooldown_s": "14400",
        },
    )
    candles = _make_candles([D("1000000") + D((i % 15) * 5000 + i * 1000) for i in range(80)])
    rules = PairRules(
        pair="BTCIDR",
        ticker_id="btc_idr",
        quantity_increment=D("0.000001"),
        price_increment=D("1000"),
        min_base_idr=D("10000"),
        min_traded_qty=D("0.00001"),
        maintenance=False,
        suspended=False,
        blocked_reasons=(),
    )
    limits = RiskLimits(
        risk_per_trade_pct=D("0.5"),
        max_daily_loss_idr=D("50000"),
        max_drawdown_pct=D("7"),
        max_consecutive_losses=4,
        max_open_positions=2,
        max_exposure_per_pair_pct=D("25"),
        max_total_exposure_pct=D("50"),
        max_order_idr=D("250000"),
        price_deviation_pct=D("0.5"),
        freshness_limit_s=60,
        cooldown_s=900,
        order_rate_limit=6,
    )
    result = run_backtest(
        candles,
        BacktestConfig(
            strategy=strat,
            limits=limits,
            rules=rules,
            paper=PaperConfig(
                slippage_pct=D("0.20"),
                partial_fill_fraction=D("0.50"),
                costs=CostModel(D("0.10"), D("0.20"), D("0.21"), D("0.00555")),
            ),
            start_equity_idr=D("1000000"),
            pair="BTCIDR",
        ),
    )
    assert strat.version_id().startswith("koro_obv_pullback-")
    assert result.origin == "BACKTEST"
    assert result.candles_used == 80
    assert result.final_equity > 0


def test_koro_owner_profile_passes_owner_defaults_checker() -> None:
    checker_path = ROOT / "deploy" / "trader" / "check_owner_defaults.py"
    spec = importlib.util.spec_from_file_location("check_owner_defaults", checker_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    profile_path = ROOT / "deploy" / "trader" / "owner-defaults.koro-rp1000000.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["status"] == "proposed"
    assert profile["limits"]["max_drawdown_pct"] == "7"
    assert mod.problems(profile) == []
