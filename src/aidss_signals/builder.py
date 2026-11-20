"""Offline SHADOW decisions from declarative rules, Kronos and AI (ADR-068).

No publisher, account or order client exists here. Models review entries only; prices
and quantities cannot be supplied by them. Run with --help for the file interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from aidss.domain.types import Candle, Timeframe
from aidss.forecasting.service import KronosForecaster
from aidss_signals.ai_review import Reviewer, parse_verdict
from aidss_trader.connector.types import Candle as RuleCandle
from aidss_trader.strategy.rules import RuleGroup, StrictModel
from aidss_trader.strategy.rules import evaluate_group as evaluate_rules


class BuilderConfig(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_ -]+$")
    symbol: str = Field(pattern=r"^[A-Z0-9]{2,24}$")
    exchange: str = Field(pattern=r"^[A-Z0-9_]{2,24}$")
    timeframe: Literal["4h", "1d"]
    entry: RuleGroup
    exit: RuleGroup
    max_data_age_seconds: int = Field(gt=0, strict=True)
    forecast_bars: int = Field(ge=1, le=30, strict=True)
    forecast_samples: int = Field(ge=1, le=10, strict=True)
    min_projected_return_pct: Decimal
    ai_min_score: int = Field(ge=0, le=100, strict=True)


class InputBar(StrictModel):
    timestamp: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def valid_bar(self) -> InputBar:
        if self.timestamp.utcoffset() != timedelta(0):
            raise ValueError("candle timestamp must be UTC aware")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("invalid OHLC range")
        return self

    def candle(self) -> Candle:
        return Candle(self.timestamp, self.open, self.high, self.low, self.close, self.volume)


class BuilderInput(StrictModel):
    long: bool = Field(strict=True)
    candles: tuple[InputBar, ...] = Field(min_length=2, max_length=1000)


def evaluate_group(group: RuleGroup, bars: list[Candle]) -> dict[str, Any]:
    return evaluate_rules(
        group, [RuleCandle(c.timestamp, c.open, c.high, c.low, c.close, c.volume) for c in bars]
    )


Forecast = Callable[[BuilderConfig, list[Candle]], dict[str, Any]]


def kronos_adapter(forecaster: KronosForecaster) -> Forecast:
    def forecast(cfg: BuilderConfig, candles: list[Candle]) -> dict[str, Any]:
        prediction = forecaster.forecast(
            cfg.symbol,
            cfg.exchange,
            Timeframe(cfg.timeframe),
            candles,
            pred_len=cfg.forecast_bars,
            sample_count=cfg.forecast_samples,
            continuous_market=True,
        )
        payload = prediction.as_payload()
        # Display rounding in as_payload can turn a cheap coin's price into zero.
        payload["bars"] = [
            {**asdict(bar), "timestamp": bar.timestamp.isoformat()} for bar in prediction.bars
        ]
        payload["last_close"] = str(candles[-1].close)
        payload["projected_return_pct"] = prediction.projected_return_pct
        payload["as_of"] = candles[-1].timestamp.isoformat()
        payload["samples"] = cfg.forecast_samples
        return payload

    return forecast


def decide(
    cfg: BuilderConfig,
    data: BuilderInput,
    now: datetime,
    forecast: Forecast,
    review: Reviewer,
) -> dict[str, Any]:
    """Decide once from immutable inputs. No result authorizes an exchange operation."""
    version = hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()
    data_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    bars = [bar.candle() for bar in data.candles]
    identity = f"{version}:{bars[-1].timestamp.isoformat()}:{data.long}"
    result: dict[str, Any] = {
        "origin": "SHADOW",
        "action": "BLOCKED",
        "reason": "invalid_data",
        "symbol": cfg.symbol,
        "exchange": cfg.exchange,
        "timeframe": cfg.timeframe,
        "config_hash": version,
        "data_hash": data_hash,
        "definition": cfg.model_dump(mode="json"),
        "id": hashlib.sha256(identity.encode()).hexdigest(),
        "as_of": bars[-1].timestamp.isoformat(),
        "generated_at": now.isoformat(),
    }
    step = timedelta(hours=4) if cfg.timeframe == "4h" else timedelta(days=1)
    if now.utcoffset() != timedelta(0):
        raise ValueError("now must be UTC aware")
    if any(b.timestamp - a.timestamp != step for a, b in zip(bars, bars[1:], strict=False)):
        result["reason"] = "unordered_or_gapped_candles"
        return result
    if bars[-1].timestamp + step > now:
        result["reason"] = "unfinished_candle"
        return result
    if now - (bars[-1].timestamp + step) > timedelta(seconds=cfg.max_data_age_seconds):
        result["reason"] = "stale_data"
        return result
    group = evaluate_group(cfg.exit if data.long else cfg.entry, bars)
    result["rules"] = group
    if not group["available"]:
        result["reason"] = "missing_indicator"
        return result
    if data.long:
        result.update(action="EXIT" if group["passed"] else "HOLD", reason="exit_rules")
        return result
    if not group["passed"]:
        result.update(action="HOLD", reason="entry_rules_not_met")
        return result
    result["candidate"] = True
    try:
        prediction = forecast(cfg, bars)
        if (
            prediction["provider"] != "huggingface"
            or prediction["ticker"] != cfg.symbol
            or prediction["exchange"] != cfg.exchange
            or prediction["timeframe"] != cfg.timeframe
            or prediction["pred_len"] != cfg.forecast_bars
            or prediction["samples"] != cfg.forecast_samples
            or prediction["as_of"] != bars[-1].timestamp.isoformat()
            or not prediction.get("model_id")
        ):
            raise ValueError("forecast provenance mismatch")
        predicted = Decimal(str(prediction["projected_return_pct"]))
        if not predicted.is_finite():
            raise ValueError("nonfinite forecast")
        projected_bars = [InputBar.model_validate(b) for b in prediction["bars"]]
        if len(projected_bars) != cfg.forecast_bars or any(
            b.timestamp != bars[-1].timestamp + step * (i + 1) for i, b in enumerate(projected_bars)
        ):
            raise ValueError("forecast horizon mismatch")
        if Decimal(str(prediction["last_close"])) != bars[-1].close:
            raise ValueError("forecast uses different candles")
        result["kronos"] = prediction
    except Exception as exc:
        result.update(reason="kronos_unavailable", error=type(exc).__name__)
        return result
    if predicted < cfg.min_projected_return_pct:
        result["reason"] = "kronos_veto"
        return result
    try:
        verdict = review(
            {
                "symbol": cfg.symbol,
                "as_of_utc": result["as_of"],
                "timeframe": cfg.timeframe,
                "rules": group,
                "kronos": prediction,
            }
        )
        verdict = parse_verdict(json.dumps(verdict.as_dict()))
        result["ai"] = verdict.as_dict()
    except Exception as exc:
        result.update(reason="ai_unavailable", error=type(exc).__name__)
        return result
    if verdict.verdict != "TAKE" or verdict.score < cfg.ai_min_score:
        result["reason"] = "ai_veto"
        return result
    result.update(action="ENTRY_CANDIDATE", reason="rules_and_required_reviews_passed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, nargs="?", help="BuilderConfig JSON")
    parser.add_argument(
        "candles", type=Path, nargs="?", help="JSON: long boolean and candles array"
    )
    parser.add_argument(
        "--schema", action="store_true", help="Print configuration and input schemas"
    )
    parser.add_argument(
        "--models", action="store_true", help="Run Kronos and configured AI gateway"
    )
    args = parser.parse_args()
    if args.schema:
        print(
            json.dumps(
                {
                    "config": BuilderConfig.model_json_schema(),
                    "input": BuilderInput.model_json_schema(),
                },
                indent=2,
            )
        )
        return
    if args.config is None or args.candles is None:
        parser.error("config and candles paths are required unless --schema is used")
    cfg = BuilderConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    data = BuilderInput.model_validate_json(args.candles.read_text(encoding="utf-8"))

    def unavailable(*_args: Any) -> Any:
        raise RuntimeError("models not enabled; use --models to request model calls")

    forecast, review = unavailable, unavailable
    if args.models:
        from aidss_signals.__main__ import _reviewer

        forecast = kronos_adapter(KronosForecaster())

        def review(dossier: dict[str, Any]) -> Any:
            return _reviewer()(dossier)

    print(json.dumps(decide(cfg, data, datetime.now(UTC), forecast, review)))


if __name__ == "__main__":
    main()
