"""One pass of the signal worker: choose coins, read them, score them, have an AI review the
candidates, and hand the survivors to a publisher.

Everything fails closed. A coin whose data would not load, a screen that could not read every
criterion, an AI that could not answer, BTC's trend unavailable: each means no signal for that coin
(or for the whole pass, in BTC's case), never a signal with the missing piece guessed.

A coin is decided at most once per daily close, so a restart or a second pass cannot publish the
same day twice, and the signal id (`aidss-<SYMBOL>-<date>`) lets the receiver refuse a repeat too.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aidss_signals.ai_review import AiUnavailable, Reviewer, build_dossier
from aidss_signals.config import SignalsConfig
from aidss_signals.market import MarketData, MarketDataError
from aidss_signals.payload import build_signal
from aidss_signals.screen import btc_bias, mechanical_levels, score_asset

BTC = "BTCUSDT"


@dataclass(slots=True)
class PassReport:
    universe: list[str] = field(default_factory=list)
    decided: int = 0
    ai_calls: int = 0
    signals: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class State:
    """The last daily candle decided per coin, kept in a small JSON file (atomic writes)."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        if path is not None and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = {str(k): str(v) for k, v in loaded.items()}
            except (OSError, ValueError):
                self._data = {}  # a damaged file restarts empty; the signal id still dedupes

    def decided(self, symbol: str, day: str) -> bool:
        return self._data.get(symbol, "") >= day

    def mark(self, symbol: str, day: str) -> None:
        self._data[symbol] = day
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            pass  # losing the marker costs a repeat decision, never a missed stop


def choose_universe(
    cfg: SignalsConfig, volumes: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """The owner's fixed symbols plus the top-N by 24h volume, each above the volume floor.
    Returns the symbols and, for each one dropped, why."""
    dropped: dict[str, str] = {}
    chosen: list[str] = []
    for symbol in cfg.fixed_symbols:
        volume = volumes.get(symbol)
        if volume is None:
            dropped[symbol] = "not_listed_or_not_a_plain_coin"
        elif volume < cfg.min_quote_volume_usdt:
            dropped[symbol] = "below_min_volume"
        else:
            chosen.append(symbol)
    ranked = sorted(volumes.items(), key=lambda kv: (-kv[1], kv[0]))
    picked = 0
    for symbol, volume in ranked:
        if picked >= cfg.top_n:
            break
        if volume < cfg.min_quote_volume_usdt:
            break
        picked += 1
        if symbol not in chosen:
            chosen.append(symbol)
    return sorted(chosen), dropped


def run_pass(
    cfg: SignalsConfig,
    market: MarketData,
    review: Reviewer,
    publish: Callable[[dict[str, Any]], None],
    now: datetime,
    state: State,
    record: Callable[[dict[str, Any]], None] = lambda _e: None,
    log: Callable[[str, str], None] = lambda _l, _m: None,
) -> PassReport:
    report = PassReport()
    try:
        volumes = market.quote_volumes()
    except MarketDataError as exc:
        report.errors.append(f"tickers: {exc}")
        log("WARN", f"signals: no tickers, no pass ({exc})")
        return report
    report.universe, dropped = choose_universe(cfg, volumes)
    for symbol, why in dropped.items():
        report.outcomes[symbol] = f"DROPPED:{why}"

    try:
        btc_candles = market.daily_candles(BTC, now)
    except MarketDataError as exc:
        # Without BTC's trend the receiver's own BTC filter cannot act, so nothing is published.
        report.errors.append(f"{BTC}: {exc}")
        log("WARN", f"signals: BTC trend unavailable, no signals this pass ({exc})")
        return report
    bias = btc_bias(btc_candles)

    for symbol in report.universe:
        try:
            candles = market.daily_candles(symbol, now)
            if not candles:
                report.outcomes[symbol] = "NO_DATA"
                continue
            day = candles[-1].timestamp.date().isoformat()
            if state.decided(symbol, day):
                report.outcomes[symbol] = "ALREADY_DECIDED"
                continue
            report.decided += 1
            state.mark(symbol, day)
            score = score_asset(candles, cfg.horizons)
            base = {
                "at": now.isoformat(),
                "symbol": symbol,
                "day": day,
                "mode": cfg.mode,
                "score_ratio": round(score.ratio, 3),
                "met": score.met,
            }
            if not score.eligible:
                report.outcomes[symbol] = f"INELIGIBLE:{score.reason}"
                record({**base, "outcome": "INELIGIBLE", "reason": score.reason})
                continue
            if score.ratio < cfg.min_score_ratio:
                report.outcomes[symbol] = "BELOW_THRESHOLD"
                record({**base, "outcome": "BELOW_THRESHOLD"})
                continue
            levels = mechanical_levels(
                score.close or 0.0, score.atr, cfg.atr_stop_multiple, cfg.tp_r
            )
            if levels is None:
                report.outcomes[symbol] = "NO_LEVELS"
                record({**base, "outcome": "NO_LEVELS"})
                continue
            if report.ai_calls >= cfg.ai_max_calls:
                report.outcomes[symbol] = "AI_BUDGET"
                record({**base, "outcome": "AI_BUDGET"})
                continue
            report.ai_calls += 1
            try:
                verdict = review(build_dossier(symbol, score, levels, bias, day))
            except AiUnavailable as exc:
                report.outcomes[symbol] = "AI_UNAVAILABLE"
                record({**base, "outcome": "AI_UNAVAILABLE", "error": str(exc)})
                log("WARN", f"signals: {symbol} dropped, AI review unavailable ({exc})")
                continue
            if verdict.verdict != "TAKE":
                report.outcomes[symbol] = "AI_SKIP"
                record({**base, "outcome": "AI_SKIP", "ai": verdict.as_dict()})
                continue
            if verdict.score < cfg.ai_min_score:
                report.outcomes[symbol] = "AI_BELOW_MIN"
                record({**base, "outcome": "AI_BELOW_MIN", "ai": verdict.as_dict()})
                continue
            signal = build_signal(symbol, day, score, levels, verdict, bias)
            report.signals.append(signal)
            report.outcomes[symbol] = "SIGNAL"
            record({**base, "outcome": "SIGNAL", "ai": verdict.as_dict(), "levels": levels})
            if cfg.mode == "PUBLISH":
                publish(signal)
            else:
                log(
                    "INFO",
                    f"signals: SHADOW signal not published: {symbol} entry {levels['entry']}",
                )
        except MarketDataError as exc:
            report.errors.append(f"{symbol}: {exc}")
            report.outcomes[symbol] = "DATA_ERROR"
            log("WARN", f"signals: {symbol} skipped ({exc})")
    return report
