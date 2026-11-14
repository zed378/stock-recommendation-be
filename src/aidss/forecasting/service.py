"""Kronos-base OHLCV time-series forecasting service.

Integrates ``NeoQuasar/Kronos-base`` and ``NeoQuasar/Kronos-Tokenizer-base``
for candlestick (K-line) forecasting over AIDSS ``Candle`` series.
PyTorch / HuggingFace dependencies are imported lazily so the platform runs
cleanly even when the optional ``[kronos]`` extra is not installed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from aidss.config import Settings, get_settings
from aidss.domain.types import Candle, Timeframe

_TIMEFRAME_DELTAS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
    Timeframe.MN1: timedelta(days=30),
}

_PREDICTOR_CACHE: dict[tuple[str, str, str, int], Any] = {}
_CACHE_LOCK = threading.Lock()


class KronosUnavailableError(RuntimeError):
    """Raised when Kronos dependencies (torch, huggingface_hub, einops) are missing."""


class KronosInsufficientDataError(ValueError):
    """Raised when there are not enough historical candles to forecast."""


@dataclass(frozen=True, slots=True)
class ForecastBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": round(self.open, 4),
            "high": round(self.high, 4),
            "low": round(self.low, 4),
            "close": round(self.close, 4),
            "volume": round(self.volume, 2),
        }


@dataclass(frozen=True, slots=True)
class KronosForecastResult:
    ticker: str
    exchange: str
    timeframe: Timeframe
    model_id: str
    tokenizer_id: str
    provider: str
    lookback_bars: int
    pred_len: int
    last_close: float
    projected_close: float
    projected_return_pct: float
    direction_bias: str
    bars: list[ForecastBar]

    def as_payload(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "exchange": self.exchange,
            "timeframe": self.timeframe.value,
            "model_id": self.model_id,
            "tokenizer_id": self.tokenizer_id,
            "provider": self.provider,
            "lookback_bars": self.lookback_bars,
            "pred_len": self.pred_len,
            "last_close": round(self.last_close, 4),
            "projected_close": round(self.projected_close, 4),
            "projected_return_pct": round(self.projected_return_pct, 4),
            "direction_bias": self.direction_bias,
            "bars": [b.as_dict() for b in self.bars],
        }


def _future_timestamps(
    last_ts: datetime, timeframe: Timeframe, pred_len: int
) -> pd.Series:
    step = _TIMEFRAME_DELTAS.get(timeframe, timedelta(days=1))
    dates: list[pd.Timestamp] = []
    cur = pd.Timestamp(last_ts)
    for _ in range(pred_len):
        cur = cur + step
        if timeframe == Timeframe.D1:
            while cur.weekday() >= 5:
                cur = cur + timedelta(days=1)
        dates.append(cur)
    return pd.Series(dates)


def _direction_bias(return_pct: float) -> str:
    if return_pct > 0.5:
        return "bullish"
    if return_pct < -0.5:
        return "bearish"
    return "neutral"


def _get_predictor(settings: Settings) -> Any:
    # Never None: KronosPredictor treats None as "pick CUDA/MPS if available".
    device = "cpu" if settings.kronos_device == "auto" else settings.kronos_device
    cache_key = (
        settings.kronos_model_id,
        settings.kronos_tokenizer_id,
        settings.kronos_device,
        settings.kronos_max_context,
    )
    with _CACHE_LOCK:
        if cache_key in _PREDICTOR_CACHE:
            return _PREDICTOR_CACHE[cache_key]

        try:
            from aidss.forecasting.kronos_model.kronos import (
                Kronos,
                KronosPredictor,
                KronosTokenizer,
            )
        except ImportError as exc:
            raise KronosUnavailableError(
                "Kronos dependencies are not installed. "
                "Install them with: pip install -e '.[kronos]'"
            ) from exc

        tokenizer = KronosTokenizer.from_pretrained(settings.kronos_tokenizer_id)
        model = Kronos.from_pretrained(settings.kronos_model_id)
        predictor = KronosPredictor(
            model,
            tokenizer,
            device=device,
            max_context=settings.kronos_max_context,
        )
        _PREDICTOR_CACHE[cache_key] = predictor
        return predictor


class KronosForecaster:
    """Runs OHLCV candlestick forecasts using NeoQuasar/Kronos-base."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def forecast(
        self,
        ticker: str,
        exchange: str,
        timeframe: Timeframe,
        candles: list[Candle],
        *,
        pred_len: int = 5,
        temperature: float = 1.0,
        top_p: float = 0.9,
        sample_count: int = 1,
    ) -> KronosForecastResult:
        if len(candles) < 20:
            raise KronosInsufficientDataError(
                "At least 20 historical candles are required for Kronos forecast; "
                f"got {len(candles)}"
            )

        window = candles[-self._settings.kronos_max_context :]
        last_close = float(window[-1].close)
        future_ts = _future_timestamps(window[-1].timestamp, timeframe, pred_len)

        if self._settings.kronos_provider == "fixture":
            bars = self._fixture_forecast(window, future_ts, pred_len)
        else:
            bars = self._model_forecast(
                window,
                future_ts,
                pred_len=pred_len,
                temperature=temperature,
                top_p=top_p,
                sample_count=sample_count,
            )

        projected_close = bars[-1].close
        ret_pct = ((projected_close - last_close) / last_close * 100.0) if last_close > 0 else 0.0

        return KronosForecastResult(
            ticker=ticker,
            exchange=exchange,
            timeframe=timeframe,
            model_id=self._settings.kronos_model_id,
            tokenizer_id=self._settings.kronos_tokenizer_id,
            provider=self._settings.kronos_provider,
            lookback_bars=len(window),
            pred_len=pred_len,
            last_close=last_close,
            projected_close=projected_close,
            projected_return_pct=ret_pct,
            direction_bias=_direction_bias(ret_pct),
            bars=bars,
        )

    def _model_forecast(
        self,
        window: list[Candle],
        future_ts: pd.Series,
        *,
        pred_len: int,
        temperature: float,
        top_p: float,
        sample_count: int,
    ) -> list[ForecastBar]:
        predictor = _get_predictor(self._settings)
        df = pd.DataFrame(
            {
                "open": [float(c.open) for c in window],
                "high": [float(c.high) for c in window],
                "low": [float(c.low) for c in window],
                "close": [float(c.close) for c in window],
                "volume": [float(c.volume) for c in window],
            }
        )
        x_ts = pd.Series([pd.Timestamp(c.timestamp) for c in window])
        pred_df = predictor.predict(
            df=df,
            x_timestamp=x_ts,
            y_timestamp=future_ts,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )
        bars: list[ForecastBar] = []
        for ts, row in pred_df.iterrows():
            o, hi, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            # The model samples each field independently, so a raw bar can have
            # its high below its open. Widen the range to contain the body.
            bars.append(
                ForecastBar(
                    timestamp=pd.Timestamp(ts).to_pydatetime(),
                    open=o,
                    high=max(o, hi, lo, c),
                    low=min(o, hi, lo, c),
                    close=c,
                    volume=max(0.0, float(row.get("volume", 0.0))),
                )
            )
        return bars

    def _fixture_forecast(
        self,
        window: list[Candle],
        future_ts: pd.Series,
        pred_len: int,
    ) -> list[ForecastBar]:
        """Deterministic OHLCV projection for CI and fixture mode."""
        closes = [float(c.close) for c in window[-10:]]
        avg_step = (closes[-1] - closes[0]) / max(1, len(closes) - 1)
        prev_close = float(window[-1].close)
        avg_vol = sum(float(c.volume) for c in window[-10:]) / 10.0

        bars: list[ForecastBar] = []
        for idx in range(pred_len):
            ts = pd.Timestamp(future_ts.iloc[idx]).to_pydatetime()
            next_close = max(0.01, prev_close + avg_step * 0.5)
            spread = max(0.01, abs(next_close - prev_close) * 0.5 + prev_close * 0.005)
            bars.append(
                ForecastBar(
                    timestamp=ts,
                    open=prev_close,
                    high=max(prev_close, next_close) + spread,
                    low=max(0.01, min(prev_close, next_close) - spread),
                    close=next_close,
                    volume=avg_vol,
                )
            )
            prev_close = next_close
        return bars
