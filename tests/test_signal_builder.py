"""Synthetic evidence only: no exchange, gateway or model download."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aidss.domain.types import Timeframe
from aidss.forecasting.service import _future_timestamps
from aidss_signals.ai_review import Verdict
from aidss_signals.builder import BuilderConfig, BuilderInput, decide, evaluate_group

NOW = datetime(2026, 11, 20, 4, tzinfo=UTC)


def config():
    rule = {
        "name": "above level",
        "left": {"indicator": "close"},
        "operator": "gt",
        "right": {"indicator": "constant", "value": "100"},
    }
    return BuilderConfig.model_validate(
        {
            "name": "fixture only",
            "symbol": "BTCIDR",
            "exchange": "INDODAX",
            "timeframe": "4h",
            "entry": {"mode": "ALL", "rules": [rule]},
            "exit": {"mode": "ANY", "rules": [{**rule, "operator": "lt"}]},
            "max_data_age_seconds": 60,
            "forecast_bars": 1,
            "forecast_samples": 1,
            "min_projected_return_pct": "0",
            "ai_min_score": 70,
        }
    )


def data(long=False, close="110"):
    return BuilderInput.model_validate(
        {
            "long": long,
            "candles": [
                {
                    "timestamp": NOW - timedelta(hours=8 - i * 4),
                    "open": "100",
                    "high": "120",
                    "low": "80",
                    "close": close,
                    "volume": "10",
                }
                for i in range(2)
            ],
        }
    )


def forecast(cfg, bars):
    return {
        "provider": "huggingface",
        "ticker": cfg.symbol,
        "exchange": cfg.exchange,
        "timeframe": cfg.timeframe,
        "pred_len": 1,
        "model_id": "synthetic-test-double",
        "last_close": str(bars[-1].close),
        "projected_return_pct": 1,
        "samples": cfg.forecast_samples,
        "as_of": bars[-1].timestamp.isoformat(),
        "bars": [
            {
                "timestamp": NOW.isoformat(),
                "open": "110",
                "high": "120",
                "low": "100",
                "close": "111.1",
                "volume": "10",
            }
        ],
    }


def take(_):
    return Verdict(80, "TAKE", "MEDIUM", (), ())


def forbidden(*_):
    pytest.fail("models must not be called")


def test_models_cannot_create_entry_and_exit_never_calls_models():
    held = decide(config(), data(close="90"), NOW, forbidden, forbidden)
    assert held["action"] == "HOLD"
    exited = decide(config(), data(long=True, close="90"), NOW, forbidden, forbidden)
    assert exited["action"] == "EXIT"
    assert "ai" not in exited and "kronos" not in exited


def test_candidate_has_shadow_provenance_and_stable_identity():
    result = decide(config(), data(), NOW, forecast, take)
    assert result["action"] == "ENTRY_CANDIDATE" and result["origin"] == "SHADOW"
    assert result["id"] == decide(config(), data(), NOW, forecast, take)["id"]
    assert result["rules"]["rules"][0]["left"] == "110"


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "fixture"},
        {"projected_return_pct": float("nan")},
        {"ticker": "ETHIDR"},
        {"bars": []},
        {"last_close": "999"},
        {"as_of": "2020-01-01T00:00:00+00:00"},
        {"samples": 999},
    ],
)
def test_invalid_forecast_blocks_candidate(change):
    def bad(cfg, bars):
        return {**forecast(cfg, bars), **change}

    result = decide(config(), data(), NOW, bad, forbidden)
    assert result["action"] == "BLOCKED" and result["reason"] == "kronos_unavailable"


def test_kronos_and_ai_veto_cannot_be_removed():
    result = decide(
        config(),
        data(),
        NOW,
        lambda c, b: {**forecast(c, b), "projected_return_pct": -1},
        forbidden,
    )
    assert result["reason"] == "kronos_veto"
    for verdict in (Verdict(90, "SKIP", "HIGH", (), ()), Verdict(69, "TAKE", "LOW", (), ())):
        result = decide(config(), data(), NOW, forecast, lambda _, v=verdict: v)
        assert result["action"] == "BLOCKED" and result["reason"] == "ai_veto"


@pytest.mark.parametrize("stage", ["forecast", "review"])
def test_model_failure_blocks_candidate(stage):
    def broken(*_):
        raise TimeoutError()

    result = decide(
        config(),
        data(),
        NOW,
        broken if stage == "forecast" else forecast,
        broken if stage == "review" else take,
    )
    assert result["action"] == "BLOCKED"


@pytest.mark.parametrize("seconds,reason", [(-1, "unfinished_candle"), (61, "stale_data")])
def test_unfinished_and_stale_data_block_before_models(seconds, reason):
    result = decide(config(), data(), NOW + timedelta(seconds=seconds), forbidden, forbidden)
    assert result["reason"] == reason and result["action"] == "BLOCKED"


def test_any_group_with_missing_indicator_is_unavailable():
    raw = config().model_dump(mode="json")
    raw["entry"]["mode"] = "ANY"
    raw["entry"]["rules"].append(
        {
            "name": "history missing",
            "left": {"indicator": "ema", "period": 20},
            "operator": "gt",
            "right": {"indicator": "close"},
        }
    )
    result = decide(BuilderConfig.model_validate(raw), data(), NOW, forbidden, forbidden)
    assert result["reason"] == "missing_indicator"


def test_crossovers_require_previous_side_and_strict_current_side():
    raw = config().model_dump(mode="json")
    raw["entry"]["rules"][0]["operator"] = "crosses_above"
    cfg = BuilderConfig.model_validate(raw)
    d = data().model_dump(mode="json")
    d["candles"][0]["close"] = "100"
    candles = [c.candle() for c in BuilderInput.model_validate(d).candles]
    assert evaluate_group(cfg.entry, candles)["passed"]
    assert not evaluate_group(cfg.entry, [c.candle() for c in data().candles])["passed"]


def test_configuration_is_strict_and_no_threshold_is_defaulted():
    raw = config().model_dump(mode="json")
    del raw["ai_min_score"]
    with pytest.raises(ValidationError):
        BuilderConfig.model_validate(raw)
    raw = data().model_dump(mode="json")
    raw["candles"][0]["close"] = "NaN"
    with pytest.raises(ValidationError):
        BuilderInput.model_validate(raw)


def test_gapped_candles_block_before_models():
    raw = data().model_dump(mode="json")
    raw["candles"][0]["timestamp"] = NOW - timedelta(hours=12)
    result = decide(config(), BuilderInput.model_validate(raw), NOW, forbidden, forbidden)
    assert result["reason"] == "unordered_or_gapped_candles"


def test_crypto_daily_calendar_includes_weekends_and_stock_default_skips_them():
    friday = datetime(2026, 11, 20, tzinfo=UTC)
    crypto = _future_timestamps(friday, Timeframe.D1, 3, continuous_market=True)
    stock = _future_timestamps(friday, Timeframe.D1, 1)
    assert [t.weekday() for t in crypto] == [5, 6, 0]
    assert stock.iloc[0].weekday() == 0


def test_cli_exports_required_configuration_without_initializing_models(monkeypatch, capsys):
    import json

    from aidss_signals import builder

    monkeypatch.setattr("sys.argv", ["builder", "--schema"])
    monkeypatch.setattr(builder, "KronosForecaster", forbidden)
    builder.main()
    schemas = json.loads(capsys.readouterr().out)
    assert "ai_min_score" in schemas["config"]["required"]
    assert "max_data_age_seconds" in schemas["config"]["required"]
    assert schemas["config"]["additionalProperties"] is False


def test_kronos_adapter_requests_crypto_calendar_and_keeps_unrounded_prices():
    from decimal import Decimal
    from types import SimpleNamespace

    from aidss.forecasting.service import ForecastBar
    from aidss_signals.builder import kronos_adapter

    def run(*args, **kwargs):
        assert kwargs["continuous_market"] is True
        assert kwargs["sample_count"] == config().forecast_samples
        bar = ForecastBar(NOW, 0.000001, 0.000002, 0.0000005, 0.0000015, 10)
        return SimpleNamespace(
            as_payload=lambda: {"last_close": 0, "bars": []},
            bars=[bar], projected_return_pct=0.123456789,
        )

    bars = [c.candle() for c in data().candles]
    payload = kronos_adapter(SimpleNamespace(forecast=run))(config(), bars)
    assert Decimal(payload["last_close"]) == bars[-1].close
    assert payload["bars"][0]["close"] == 0.0000015
    assert payload["projected_return_pct"] == 0.123456789
