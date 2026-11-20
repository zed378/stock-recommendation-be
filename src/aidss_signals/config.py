"""Configuration from the environment. Off by default, and no number has a default: an unset one
stops the worker and names what is missing, because a signal produced from a value nobody chose is
how a screen turns into a guess (the owner's rule for every trading number, OQ-11)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PREFIX = "AIDSS_SIGNALS_"
DEFAULT_TOP_N = 5  # the owner's own default for how many coins are picked by volume (2026-11-20)
MAX_TOP_N = 50  # a resource limit (one candle request per coin), not a recommendation
VALID_HORIZONS = ("1d", "7d", "14d", "30d")
SYMBOL = re.compile(r"^[A-Z0-9]{2,15}USDT$")
#: Enough daily bars for the longest criterion (the 200-bar average and the 60-bar return).
MIN_DAILY_BARS = 201


class ConfigError(Exception):
    """One or more settings are missing or invalid; the message lists all of them."""


@dataclass(frozen=True, slots=True)
class H4Config:
    """The 4-hour breakout signals' settings as the worker uses them."""

    strategies: tuple[str, ...]
    donchian_n: int
    vol_period: int
    vol_mult: float
    range_mult: float
    min_score: int
    allow_short: bool
    max_hold_bars: int
    fee_pct: float
    slippage_pct: float
    drift_r: float


@dataclass(frozen=True, slots=True)
class SignalsConfig:
    mode: str  # SHADOW: nothing leaves the process. PUBLISH: signals go to connected receivers
    fixed_symbols: tuple[str, ...]
    top_n: int
    min_quote_volume_usdt: Decimal
    horizons: tuple[str, ...]
    min_score_ratio: float
    atr_stop_multiple: float
    tp_r: tuple[float, float, float]
    ai_min_score: int
    ai_max_calls: int
    klines_base: str
    host: str
    port: int
    state_path: Path
    decision_log_path: Path
    ack_log_path: Path
    client_token: str = field(repr=False, default="")
    notes: tuple[str, ...] = ()
    h4: H4Config | None = None


def load_config(env: Mapping[str, str] | None = None) -> SignalsConfig | None:
    """None when the worker is switched off; raises `ConfigError` listing every problem."""
    env = os.environ if env is None else env
    if env.get(PREFIX + "ENABLED", "").strip().lower() != "true":
        return None
    problems: list[str] = []
    notes: list[str] = []

    def raw(name: str) -> str:
        return env.get(PREFIX + name, "").strip()

    def number(name: str) -> float:
        text = raw(name)
        try:
            value = float(text)
        except ValueError:
            problems.append(f"{PREFIX}{name} is required and must be a number")
            return float("nan")
        if value != value or value in (float("inf"), float("-inf")):
            problems.append(f"{PREFIX}{name} must be a finite number")
        return value

    fixed = tuple(s.strip().upper() for s in raw("SYMBOLS").split(",") if s.strip())
    for s in fixed:
        if not SYMBOL.match(s):
            problems.append(f"{PREFIX}SYMBOLS: {s} is not a USDT symbol such as BTCUSDT")
    if len(set(fixed)) != len(fixed):
        problems.append(f"{PREFIX}SYMBOLS has a duplicate")

    # The one number with a default, because the owner chose it: five coins by 24h volume, and the
    # owner may set any whole number from 0 (none) to the resource cap.
    top_text = raw("TOP_N")
    top_n = float(DEFAULT_TOP_N) if top_text == "" else number("TOP_N")
    if top_n == top_n and not (float(top_n).is_integer() and 0 <= top_n <= MAX_TOP_N):
        problems.append(f"{PREFIX}TOP_N must be a whole number from 0 to {MAX_TOP_N}")
    if not fixed and top_n == 0:
        problems.append("nothing to scan: set SYMBOLS, or TOP_N above 0")

    try:
        min_volume = Decimal(raw("MIN_QUOTE_VOLUME_USDT"))
        if min_volume <= 0:
            raise InvalidOperation
    except InvalidOperation:
        problems.append(f"{PREFIX}MIN_QUOTE_VOLUME_USDT is required and must be above 0")
        min_volume = Decimal(0)

    horizons = tuple(h.strip() for h in raw("HORIZONS").split(",") if h.strip())
    if (
        not horizons
        or any(h not in VALID_HORIZONS for h in horizons)
        or len(set(horizons)) != len(horizons)
    ):
        problems.append(f"{PREFIX}HORIZONS is required: a list from {', '.join(VALID_HORIZONS)}")

    ratio = number("MIN_SCORE_RATIO")
    if ratio == ratio and not 0 < ratio <= 1:
        problems.append(f"{PREFIX}MIN_SCORE_RATIO must be above 0 and at most 1")
    atr_mult = number("ATR_STOP_MULTIPLE")
    if atr_mult == atr_mult and atr_mult <= 0:
        problems.append(f"{PREFIX}ATR_STOP_MULTIPLE must be positive")
    r1, r2, r3 = number("TP_R1"), number("TP_R2"), number("TP_R3")
    if all(v == v for v in (r1, r2, r3)) and not 0 < r1 < r2 < r3:
        problems.append("need 0 < TP_R1 < TP_R2 < TP_R3")
    ai_min = number("AI_MIN_SCORE")
    if ai_min == ai_min and not (float(ai_min).is_integer() and 1 <= ai_min <= 100):
        problems.append(f"{PREFIX}AI_MIN_SCORE must be a whole number from 1 to 100")
    ai_calls = number("AI_MAX_CALLS")
    if ai_calls == ai_calls and not (float(ai_calls).is_integer() and 1 <= ai_calls <= 50):
        problems.append(f"{PREFIX}AI_MAX_CALLS must be a whole number from 1 to 50")

    mode = raw("MODE").upper() or "SHADOW"
    if mode not in ("SHADOW", "PUBLISH"):
        problems.append(f"{PREFIX}MODE must be SHADOW or PUBLISH")
    elif mode == "PUBLISH" and raw("CONFIRM_PUBLISH").lower() != "yes":
        notes.append(f"{PREFIX}MODE=PUBLISH needs {PREFIX}CONFIRM_PUBLISH=yes; running in SHADOW")
        mode = "SHADOW"

    token = raw("CLIENT_TOKEN")
    if mode == "PUBLISH" and len(token) < 16:
        problems.append(f"{PREFIX}CLIENT_TOKEN must be at least 16 characters to publish")
    port_text = raw("PORT") or "0"
    if not port_text.isdigit() or not 0 <= int(port_text) <= 65535:
        problems.append(f"{PREFIX}PORT must be a port number")

    base = (raw("KLINES_BASE") or "https://api.binance.com").rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", base):
        problems.append(f"{PREFIX}KLINES_BASE must be an https origin")

    if problems:
        raise ConfigError("; ".join(problems))
    data = Path(raw("DATA_DIR") or "data")
    return SignalsConfig(
        mode=mode,
        fixed_symbols=fixed,
        top_n=int(top_n),
        min_quote_volume_usdt=min_volume,
        horizons=horizons,
        min_score_ratio=ratio,
        atr_stop_multiple=atr_mult,
        tp_r=(r1, r2, r3),
        ai_min_score=int(ai_min),
        ai_max_calls=int(ai_calls),
        klines_base=base,
        host=raw("HOST") or "127.0.0.1",
        port=int(port_text),
        state_path=data / "signals-state.json",
        decision_log_path=data / "signals-decisions.jsonl",
        ack_log_path=data / "signals-acks.jsonl",
        client_token=token,
        notes=tuple(notes),
    )


def config_from_settings(settings: Any, env: Mapping[str, str] | None = None) -> SignalsConfig:
    """The worker's config from the owner's database settings (ADR-066), plus the few things that
    are not the owner's to set from a screen: where candles come from, where the receiver listens,
    and its secret token. `settings` is `aidss_trader.signals_config.SignalSettings`; the caller
    checks that nothing is unset first."""
    env = os.environ if env is None else env
    data = Path(env.get(PREFIX + "DATA_DIR", "").strip() or "data")
    token = env.get(PREFIX + "CLIENT_TOKEN", "").strip()
    port_text = env.get(PREFIX + "PORT", "").strip() or "0"
    base = (env.get(PREFIX + "KLINES_BASE", "").strip() or "https://api.binance.com").rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d+)?", base):
        raise ConfigError(f"{PREFIX}KLINES_BASE must be an https origin")
    if not port_text.isdigit() or not 0 <= int(port_text) <= 65535:
        raise ConfigError(f"{PREFIX}PORT must be a port number")
    h = settings.h4
    h4 = None
    if h.enabled:
        h4 = H4Config(
            strategies=tuple(h.strategies),
            donchian_n=int(h.donchian_n),
            vol_period=int(h.vol_period),
            vol_mult=float(h.vol_mult),
            range_mult=float(h.range_mult),
            min_score=int(h.min_score),
            allow_short=bool(h.allow_short),
            max_hold_bars=int(h.max_hold_bars),
            fee_pct=float(h.fee_pct),
            slippage_pct=float(h.slippage_pct),
            drift_r=float(h.drift_r),
        )
    return SignalsConfig(
        h4=h4,
        mode=settings.mode,
        fixed_symbols=tuple(settings.symbols),
        top_n=settings.top_n,
        min_quote_volume_usdt=settings.min_quote_volume_usdt,
        horizons=tuple(settings.horizons),
        min_score_ratio=float(settings.min_score_ratio),
        atr_stop_multiple=float(settings.atr_stop_multiple),
        tp_r=tuple(float(v) for v in settings.tp_r),  # type: ignore[arg-type]
        ai_min_score=int(settings.ai_min_score),
        ai_max_calls=int(settings.ai_max_calls),
        klines_base=base,
        host=env.get(PREFIX + "HOST", "").strip() or "127.0.0.1",
        port=int(port_text),
        state_path=data / "signals-state.json",
        decision_log_path=data / "signals-decisions.jsonl",
        ack_log_path=data / "signals-acks.jsonl",
        client_token=token,
    )
