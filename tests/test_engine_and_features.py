"""Indicator Engine persistence and Feature Engineering tests (Phase 3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from aidss.collectors.market_data import MarketDataCollector
from aidss.config import Settings
from aidss.db.models import FeatureSnapshot, TechnicalIndicator
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine, IndicatorSpec, compute
from aidss.indicators.features import compute_features, persist_features
from aidss.plugins.registry import get_market_data_provider
from tests.conftest import make_candles


@pytest.fixture
def asset(session):
    collector = MarketDataCollector(
        get_market_data_provider(Settings(market_data_provider="fixture"))
    )
    asset = collector.get_or_create_asset(session, "BBCA")
    end = datetime(2025, 6, 1, tzinfo=UTC)
    collector.collect(session, asset, Timeframe.D1, end - timedelta(days=400), end)
    return asset


# --- Engine ----------------------------------------------------------------


def test_params_key_is_order_independent() -> None:
    a = IndicatorSpec("macd", {"fast": 12, "slow": 26, "signal": 9})
    b = IndicatorSpec("macd", {"signal": 9, "slow": 26, "fast": 12})
    assert a.params_key == b.params_key


def test_unknown_indicator_name_is_rejected(candles) -> None:
    from aidss.indicators.engine import candles_to_frame

    with pytest.raises(ValueError, match="macdd"):
        compute(candles_to_frame(candles), IndicatorSpec("macdd", {}))


def test_snapshot_covers_every_configured_indicator(candles) -> None:
    snapshot = IndicatorEngine().snapshot(candles)
    assert snapshot["bars"] == len(candles)
    names = {key.split("(")[0] for key in snapshot["indicators"]}
    assert {"sma", "ema", "rsi", "macd", "bollinger", "atr", "adx"} <= names
    assert "support" in snapshot["levels"]
    assert snapshot["breakout"]["direction"] in {"bullish", "bearish", "none"}


def test_snapshot_contains_no_nan(candles) -> None:
    """NaN has no JSON representation; warm-up gaps must surface as null."""
    snapshot = IndicatorEngine().snapshot(candles)
    for payload in snapshot["indicators"].values():
        for value in payload.values():
            assert value is None or isinstance(value, (int, float))
            if isinstance(value, float):
                assert value == value  # NaN is the only value unequal to itself


def test_snapshot_of_an_empty_series_is_safe() -> None:
    snapshot = IndicatorEngine().snapshot([])
    assert snapshot["bars"] == 0
    assert snapshot["indicators"] == {}


def test_persist_writes_rows_and_skips_warmup(session, asset) -> None:
    from aidss.collectors.market_data import load_candles

    candles = load_candles(session, asset.id, Timeframe.D1)
    report = IndicatorEngine().persist(session, asset.id, Timeframe.D1, candles)

    assert report.inserted > 0
    assert report.skipped_all_null > 0, "warm-up bars should not be stored as empty rows"

    stored = session.scalar(
        select(func.count())
        .select_from(TechnicalIndicator)
        .where(TechnicalIndicator.asset_id == asset.id)
    )
    assert stored == report.inserted


def test_persist_is_idempotent(session, asset) -> None:
    from aidss.collectors.market_data import load_candles

    candles = load_candles(session, asset.id, Timeframe.D1)
    engine = IndicatorEngine()
    first = engine.persist(session, asset.id, Timeframe.D1, candles)
    second = engine.persist(session, asset.id, Timeframe.D1, candles)

    assert first.inserted > 0
    assert second.inserted == 0
    assert second.updated == 0


def test_same_indicator_with_different_periods_coexists(session, asset) -> None:
    from aidss.collectors.market_data import load_candles

    candles = load_candles(session, asset.id, Timeframe.D1)
    engine = IndicatorEngine(
        specs=(IndicatorSpec("rsi", {"period": 14}), IndicatorSpec("rsi", {"period": 7}))
    )
    engine.persist(session, asset.id, Timeframe.D1, candles)

    keys = set(
        session.scalars(
            select(TechnicalIndicator.params_key).where(
                TechnicalIndicator.indicator_name == "rsi"
            )
        ).all()
    )
    assert keys == {"period=14", "period=7"}


# --- Features --------------------------------------------------------------


def test_features_report_expected_keys(candles) -> None:
    features = compute_features(candles)
    for key in (
        "return_1b",
        "return_20b",
        "volatility_20b",
        "drawdown_current",
        "drawdown_max",
        "range_position_52b",
        "gap_from_sma20",
    ):
        assert key in features


def test_return_matches_manual_computation(candles) -> None:
    features = compute_features(candles)
    expected = float(candles[-1].close) / float(candles[-2].close) - 1.0
    assert features["return_1b"] == pytest.approx(expected)


def test_features_missing_data_reported_as_none_not_zero() -> None:
    features = compute_features(make_candles(count=5))
    assert features["return_60b"] is None
    assert features["volatility_20b"] is None
    # Zero would read as "no volatility"; None reads as "not enough data".
    assert features["return_1b"] is not None


def test_drawdown_is_never_positive(candles) -> None:
    features = compute_features(candles)
    assert features["drawdown_current"] <= 0
    assert features["drawdown_max"] <= features["drawdown_current"] + 1e-12


def test_range_position_is_bounded(candles) -> None:
    position = compute_features(candles)["range_position_52b"]
    assert 0.0 <= position <= 1.0


def test_empty_series_yields_zero_bars() -> None:
    assert compute_features([])["bars"] == 0


def test_persist_features_upserts(session, asset) -> None:
    from aidss.collectors.market_data import load_candles

    candles = load_candles(session, asset.id, Timeframe.D1)
    persist_features(session, asset.id, Timeframe.D1, candles)
    persist_features(session, asset.id, Timeframe.D1, candles)

    count = session.scalar(
        select(func.count())
        .select_from(FeatureSnapshot)
        .where(FeatureSnapshot.asset_id == asset.id)
    )
    assert count == 1
