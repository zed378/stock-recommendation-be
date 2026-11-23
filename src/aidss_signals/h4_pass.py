"""One pass of the 4-hour breakout signals: find setups on the coins just closed, store each with a
deterministic id, publish it when the owner has said so, and follow every unfinished signal to its
simulated outcome (ADR-067).

Same discipline as the daily screen: SHADOW by default, a failure for one coin never stops the
others, and BTC's trend being unavailable stops the pass rather than guessing. A signal's id is
derived from its candle, so running a pass twice, restarting or replaying cannot store or publish it
twice.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from aidss_signals import atlas, h4
from aidss_signals.config import MIN_DAILY_BARS, SignalsConfig
from aidss_signals.lifecycle import CLOSED, SimParams, simulate
from aidss_signals.market import MarketData, MarketDataError
from aidss_signals.store import SignalStore
from aidss_signals.worker import choose_universe

BTC = "BTCUSDT"
CANDLES = 300  # enough for the 200-bar trend and every window the owner can choose
SLOT_OFFSET = timedelta(minutes=5)  # after a 4H close, once the exchange has settled the candle
LABELS = {
    h4.DONCHIAN: "aidss_donchian_4h",
    h4.SPIKE: "aidss_spike_4h",
    h4.ATLAS: "aidss_atlas_4h",
}


@dataclass(slots=True)
class H4Report:
    universe: list[str] = field(default_factory=list)
    new_signals: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)
    tracked: int = 0
    closed: int = 0
    errors: list[str] = field(default_factory=list)


def _why(shortlist: atlas.Shortlist) -> str:
    counts: dict[str, int] = {}
    for reason in shortlist.rejected.values():
        key = reason.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    return (
        ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no coins with enough history"
    )


def h4_slot(now: datetime) -> datetime:
    """The most recent scheduled 4H pass time at or before `now` (00, 04, 08 ... UTC plus 5 min)."""
    hour = now.hour - now.hour % 4
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0) + SLOT_OFFSET
    return slot if slot <= now else slot - timedelta(hours=4)


def btc_trend_4h(candles: list[Any]) -> str:
    """ "bullish" when the close is above its 50-bar average and that is above the 200-bar average,
    "bearish" for the mirror, "choppy" for anything mixed, and "" with too little data."""
    if len(candles) < MIN_DAILY_BARS:
        return ""
    closes = [float(c.close) for c in candles]
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / 200
    last = closes[-1]
    if last > sma50 > sma200:
        return "bullish"
    if last < sma50 < sma200:
        return "bearish"
    return "choppy"


def _strength(score: int) -> str:
    return "HIGH" if score >= 80 else ("MEDIUM" if score >= 60 else "LOW")


def signal_payload(
    setup: h4.Setup, symbol: str, sid: str, lv: dict[str, float], bias: str
) -> dict[str, Any]:
    return {
        "id": sid,
        "symbol": symbol,
        "side": setup.side,
        "entryPrice": lv["entry"],
        "sl": lv["stop"],
        "tp1": lv["tp1"],
        "tp2": lv["tp2"],
        "tp3": lv["tp3"],
        "strategy": LABELS[setup.strategy],
        "score": setup.score,
        "strength": _strength(setup.score),
        "btcTrendBias": bias,
        "analytics": {
            "source": "aidss-signals-4h",
            "timeframe": "4h",
            "candle_open": setup.candle_open.isoformat(),
            "components": setup.components,
            "note": "a rank from a transparent point system, not a probability",
        },
    }


def run_h4_pass(
    cfg: SignalsConfig,
    store: SignalStore,
    market: MarketData,
    scan_id: uuid.UUID,
    publish: Callable[[dict[str, Any]], None],
    now: datetime,
    log: Callable[[str, str], None] = lambda _l, _m: None,
) -> H4Report:
    report = H4Report()
    h = cfg.h4
    if h is None:
        return report
    params = h4.H4Params(h.donchian_n, h.vol_period, h.vol_mult, h.range_mult)
    try:
        volumes = market.quote_volumes()
        btc = market.candles(BTC, "4h", now, CANDLES)
    except MarketDataError as exc:
        report.errors.append(str(exc))
        log("WARN", f"signals 4h: no pass ({exc})")
        return report
    bias = btc_trend_4h(btc)
    if bias == "":
        report.errors.append("BTC 4H trend unavailable")
        log("WARN", "signals 4h: BTC trend unavailable, no signals this pass")
        return report
    report.universe, dropped = choose_universe(cfg, volumes)
    for symbol, why in dropped.items():
        report.outcomes[symbol] = f"DROPPED:{why}"

    seen: dict[str, list[Any]] = {BTC: btc}
    for symbol in report.universe:
        try:
            seen[symbol] = seen.get(symbol) or market.candles(symbol, "4h", now, CANDLES)
        except MarketDataError as exc:
            report.errors.append(f"{symbol}: {exc}")
            report.outcomes[symbol] = "DATA_ERROR"

    shortlist: atlas.Shortlist | None = None
    if h4.ATLAS in h.strategies:
        chars = {}
        for symbol in report.universe:
            ch = atlas.character(seen[symbol]) if symbol in seen else None
            if ch is not None:
                chars[symbol] = ch
        v24 = {s: float(volumes.get(s, 0)) for s in chars}
        shortlist = atlas.cascade(chars, v24, len(report.universe))
        if not shortlist.picks:
            log("INFO", f"signals 4h: atlas shortlist empty ({_why(shortlist)})")

    for symbol in report.universe:
        if report.outcomes.get(symbol) == "DATA_ERROR":
            continue
        try:
            candles = seen[symbol]
            pick = None if shortlist is None else shortlist.picks.get(symbol)
            setup = h4.detect(
                candles,
                params,
                h.strategies,
                bias,
                h.allow_short,
                None if pick is None else (pick, shortlist.k),
            )
            if setup is None:
                why = "" if shortlist is None else shortlist.rejected.get(symbol, "")
                report.outcomes[symbol] = f"NO_SETUP:{why}" if why else "NO_SETUP"
                continue
            if setup.score < h.min_score:
                report.outcomes[symbol] = f"BELOW_MIN_SCORE:{setup.score}"
                continue
            lv = h4.levels(setup.side, setup.entry, setup.atr, cfg.atr_stop_multiple, cfg.tp_r)
            if lv is None:
                report.outcomes[symbol] = "NO_LEVELS"
                continue
            sid = h4.signal_id(setup.strategy, symbol, setup.side, setup.candle_open)
            issued = setup.candle_open + h4.H4
            added = store.add_trade(
                scan_id,
                {
                    "signal_id": sid,
                    "strategy": setup.strategy,
                    "symbol": symbol,
                    "side": setup.side,
                    "mode": cfg.mode,
                    "candle_open": setup.candle_open,
                    "issued_at": issued,
                    "score": setup.score,
                    "components": setup.components,
                    "entry": lv["entry"],
                    "stop": lv["stop"],
                    "tp1": lv["tp1"],
                    "tp2": lv["tp2"],
                    "tp3": lv["tp3"],
                    "atr": setup.atr,
                    "btc_bias": bias,
                },
            )
            if not added:
                report.outcomes[symbol] = "ALREADY_SEEN"
                continue
            payload = signal_payload(setup, symbol, sid, lv, bias)
            report.new_signals.append(payload)
            report.outcomes[symbol] = f"SIGNAL:{setup.strategy}:{setup.side}"
            if cfg.mode == "PUBLISH":
                publish(payload)
                store.mark_published(sid)
            else:
                log("INFO", f"signals 4h: SHADOW signal not published: {sid}")
        except MarketDataError as exc:
            report.errors.append(f"{symbol}: {exc}")
            report.outcomes[symbol] = "DATA_ERROR"

    track(cfg, store, market, seen, now, report, log)
    return report


def track(
    cfg: SignalsConfig,
    store: SignalStore,
    market: MarketData,
    seen: dict[str, list[Any]],
    now: datetime,
    report: H4Report,
    log: Callable[[str, str], None] = lambda _l, _m: None,
) -> None:
    """Re-simulate every unfinished signal from the closed candles after its own. Deterministic,
    so running it twice gives the same answer; a closed or skipped signal is never touched again."""
    h = cfg.h4
    if h is None:
        return
    sim = SimParams(h.fee_pct, h.slippage_pct, h.drift_r, h.max_hold_bars)
    for t in store.unfinished_trades():
        try:
            candles = seen.get(t["symbol"])
            if candles is None:
                candles = market.candles(t["symbol"], "4h", now, CANDLES)
                seen[t["symbol"]] = candles
            after = [c for c in candles if c.timestamp > t["candle_open"]]
            out = simulate(t["side"], t["entry"], t["stop"], t["tps"], after, sim)
            closed_at = None
            if out.state == CLOSED and out.closed_index is not None:
                closed_at = after[out.closed_index].timestamp + h4.H4
            store.update_trade(t["id"], out, closed_at)
            report.tracked += 1
            report.closed += out.state in (CLOSED, "SKIPPED")
        except MarketDataError as exc:
            report.errors.append(f"track {t['symbol']}: {exc}")
            log("WARN", f"signals 4h: could not follow {t['signal_id']} ({exc})")


def utc_now() -> datetime:
    return datetime.now(UTC)
