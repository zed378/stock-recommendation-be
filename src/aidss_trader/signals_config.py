"""The crypto signal worker's settings, as the owner edits them on the operator screen (ADR-066).

Same discipline as the risk limits: **no number has a default** except the one the owner chose
(how many coins to pick by 24h volume: five), an unset number keeps the worker idle and the screen
says which, and a change that makes the worker act more readily needs a password. The receiver's
client token is a secret and is not stored here; it stays in the worker's environment.

Pure validation and storage. Nothing in this module touches a market or an exchange.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.db.models import SignalConfigRow

DEFAULT_TOP_N = 5  # the owner's own default (2026-11-20)
MAX_TOP_N = 50  # a resource limit: one candle request per coin
VALID_HORIZONS = ("1d", "7d", "14d", "30d")
SYMBOL = re.compile(r"^[A-Z0-9]{2,15}USDT$")
MODES = ("SHADOW", "PUBLISH")


class SignalSettingsError(ValueError):
    """Carries every problem found, not just the first."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


H4_STRATEGIES = ("DONCHIAN", "SPIKE")


@dataclass(frozen=True, slots=True)
class H4Settings:
    """The 4-hour breakout signals (ADR-067). Switched off until the owner turns them on; every
    number is required then, none has a default. The stop multiple and the targets are shared with
    the daily screen (the same two settings), so one place decides how a trade is priced."""

    enabled: bool = False
    strategies: tuple[str, ...] = ()
    donchian_n: int | None = None
    vol_period: int | None = None
    vol_mult: Decimal | None = None
    range_mult: Decimal | None = None
    min_score: int | None = None
    allow_short: bool = False
    max_hold_bars: int | None = None
    fee_pct: Decimal | None = None
    slippage_pct: Decimal | None = None
    drift_r: Decimal | None = None

    def as_json(self) -> dict[str, Any]:
        def d(v: Decimal | None) -> str | None:
            return None if v is None else format(v.normalize(), "f")

        return {
            "enabled": self.enabled,
            "strategies": list(self.strategies),
            "donchian_n": self.donchian_n,
            "vol_period": self.vol_period,
            "vol_mult": d(self.vol_mult),
            "range_mult": d(self.range_mult),
            "min_score": self.min_score,
            "allow_short": self.allow_short,
            "max_hold_bars": self.max_hold_bars,
            "fee_pct": d(self.fee_pct),
            "slippage_pct": d(self.slippage_pct),
            "drift_r": d(self.drift_r),
        }


@dataclass(frozen=True, slots=True)
class SignalSettings:
    enabled: bool = False
    mode: str = "SHADOW"
    symbols: tuple[str, ...] = ()
    top_n: int = DEFAULT_TOP_N
    min_quote_volume_usdt: Decimal | None = None
    horizons: tuple[str, ...] = ()
    min_score_ratio: Decimal | None = None
    atr_stop_multiple: Decimal | None = None
    tp_r: tuple[Decimal, Decimal, Decimal] | None = None
    ai_min_score: int | None = None
    ai_max_calls: int | None = None
    h4: H4Settings = H4Settings()
    notes: str = field(default="", compare=False)

    def as_json(self) -> dict[str, Any]:
        def d(v: Decimal | None) -> str | None:
            return None if v is None else format(v.normalize(), "f")

        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "symbols": list(self.symbols),
            "top_n": self.top_n,
            "min_quote_volume_usdt": d(self.min_quote_volume_usdt),
            "horizons": list(self.horizons),
            "min_score_ratio": d(self.min_score_ratio),
            "atr_stop_multiple": d(self.atr_stop_multiple),
            "tp_r": None if self.tp_r is None else [d(v) for v in self.tp_r],
            "ai_min_score": self.ai_min_score,
            "ai_max_calls": self.ai_max_calls,
            "h4": self.h4.as_json(),
        }


def _dec(value: Any, name: str, problems: list[str]) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        out = Decimal(str(value).strip())
    except InvalidOperation:
        problems.append(f"{name} must be a number")
        return None
    if not out.is_finite():
        problems.append(f"{name} must be a finite number")
        return None
    return out


def _int(value: Any, name: str, problems: list[str]) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        out = Decimal(str(value).strip())
    except InvalidOperation:
        problems.append(f"{name} must be a whole number")
        return None
    if out != out.to_integral_value():
        problems.append(f"{name} must be a whole number")
        return None
    return int(out)


def _parse_h4(raw: Any, problems: list[str]) -> H4Settings:
    if not isinstance(raw, dict):
        return H4Settings()
    strategies = tuple(
        str(x).strip().upper() for x in (raw.get("strategies") or []) if str(x).strip()
    )
    if any(x not in H4_STRATEGIES for x in strategies) or len(set(strategies)) != len(strategies):
        problems.append(f"h4.strategies must be a list from {', '.join(H4_STRATEGIES)}")

    def whole(name: str, lo: int, hi: int) -> int | None:
        v = _int(raw.get(name), f"h4.{name}", problems)
        if v is not None and not lo <= v <= hi:
            problems.append(f"h4.{name} must be from {lo} to {hi}")
        return v

    def dec(name: str, lo: Decimal, hi: Decimal, *, lo_open: bool = False) -> Decimal | None:
        v = _dec(raw.get(name), f"h4.{name}", problems)
        if v is not None and not ((lo < v) if lo_open else (lo <= v)) or (v is not None and v > hi):
            problems.append(
                f"h4.{name} must be {'above' if lo_open else 'from'} {lo} and at most {hi}"
            )
        return v

    return H4Settings(
        enabled=bool(raw.get("enabled", False)),
        strategies=strategies,
        donchian_n=whole("donchian_n", 5, 200),
        vol_period=whole("vol_period", 5, 100),
        vol_mult=dec("vol_mult", Decimal(1), Decimal(20), lo_open=True),
        range_mult=dec("range_mult", Decimal(0), Decimal(10), lo_open=True),
        min_score=whole("min_score", 1, 100),
        allow_short=bool(raw.get("allow_short", False)),
        max_hold_bars=whole("max_hold_bars", 1, 200),
        fee_pct=dec("fee_pct", Decimal(0), Decimal(5)),
        slippage_pct=dec("slippage_pct", Decimal(0), Decimal(5)),
        drift_r=dec("drift_r", Decimal(0), Decimal(3), lo_open=True),
    )


def parse_settings(body: dict[str, Any]) -> SignalSettings:
    """Validate a submitted body. Raises `SignalSettingsError` listing every problem; a blank
    number is allowed (it stays unset), a wrong one is not."""
    problems: list[str] = []
    mode = str(body.get("mode", "SHADOW")).strip().upper()
    if mode not in MODES:
        problems.append("mode must be SHADOW or PUBLISH")

    raw_symbols = body.get("symbols") or []
    if isinstance(raw_symbols, str):
        raw_symbols = raw_symbols.replace("\n", ",").split(",")
    symbols = tuple(str(x).strip().upper() for x in raw_symbols if str(x).strip())
    for sym in symbols:
        if not SYMBOL.match(sym):
            problems.append(f"{sym} is not a USDT symbol such as BTCUSDT")
    if len(set(symbols)) != len(symbols):
        problems.append("symbols has a duplicate")

    top = body.get("top_n")
    top_n = DEFAULT_TOP_N if top is None or str(top).strip() == "" else _int(top, "top_n", problems)
    if top_n is not None and not 0 <= top_n <= MAX_TOP_N:
        problems.append(f"top_n must be from 0 to {MAX_TOP_N}")

    volume = _dec(body.get("min_quote_volume_usdt"), "min_quote_volume_usdt", problems)
    if volume is not None and volume <= 0:
        problems.append("min_quote_volume_usdt must be above 0")

    raw_h = body.get("horizons") or []
    horizons = tuple(str(h).strip() for h in raw_h if str(h).strip())
    if any(h not in VALID_HORIZONS for h in horizons) or len(set(horizons)) != len(horizons):
        problems.append(f"horizons must be a list from {', '.join(VALID_HORIZONS)}")

    ratio = _dec(body.get("min_score_ratio"), "min_score_ratio", problems)
    if ratio is not None and not Decimal(0) < ratio <= Decimal(1):
        problems.append("min_score_ratio must be above 0 and at most 1")
    atr = _dec(body.get("atr_stop_multiple"), "atr_stop_multiple", problems)
    if atr is not None and atr <= 0:
        problems.append("atr_stop_multiple must be positive")

    raw_tp = body.get("tp_r")
    tp: tuple[Decimal, Decimal, Decimal] | None = None
    if raw_tp is not None and any(str(x).strip() != "" for x in raw_tp):
        if len(raw_tp) != 3:
            problems.append("tp_r needs three numbers")
        else:
            parts = [_dec(x, "tp_r", problems) for x in raw_tp]
            if all(v is not None for v in parts):
                a, b, c = parts  # type: ignore[misc]
                if not Decimal(0) < a < b < c:
                    problems.append("need 0 < tp_r[0] < tp_r[1] < tp_r[2]")
                else:
                    tp = (a, b, c)

    ai_min = _int(body.get("ai_min_score"), "ai_min_score", problems)
    if ai_min is not None and not 1 <= ai_min <= 100:
        problems.append("ai_min_score must be from 1 to 100")
    ai_calls = _int(body.get("ai_max_calls"), "ai_max_calls", problems)
    if ai_calls is not None and not 1 <= ai_calls <= 50:
        problems.append("ai_max_calls must be from 1 to 50")

    h4 = _parse_h4(body.get("h4"), problems)

    if problems:
        raise SignalSettingsError(problems)
    return SignalSettings(
        enabled=bool(body.get("enabled", False)),
        mode=mode,
        symbols=symbols,
        top_n=top_n if top_n is not None else DEFAULT_TOP_N,
        min_quote_volume_usdt=volume,
        horizons=horizons,
        min_score_ratio=ratio,
        atr_stop_multiple=atr,
        tp_r=tp,
        ai_min_score=ai_min,
        ai_max_calls=ai_calls,
        h4=h4,
        notes=str(body.get("notes", ""))[:200],
    )


def unset_fields(s: SignalSettings) -> list[str]:
    """What still has to be chosen before the worker may run. Empty means ready."""
    missing: list[str] = []
    if not s.symbols and s.top_n == 0:
        missing.append("symbols_or_top_n")
    if s.min_quote_volume_usdt is None:
        missing.append("min_quote_volume_usdt")
    if not s.horizons:
        missing.append("horizons")
    if s.min_score_ratio is None:
        missing.append("min_score_ratio")
    if s.atr_stop_multiple is None:
        missing.append("atr_stop_multiple")
    if s.tp_r is None:
        missing.append("tp_r")
    if s.ai_min_score is None:
        missing.append("ai_min_score")
    if s.ai_max_calls is None:
        missing.append("ai_max_calls")
    if s.h4.enabled:
        h = s.h4
        for name in (
            "donchian_n",
            "vol_period",
            "vol_mult",
            "range_mult",
            "min_score",
            "max_hold_bars",
            "fee_pct",
            "slippage_pct",
            "drift_r",
        ):
            if getattr(h, name) is None:
                missing.append(f"h4.{name}")
        if not h.strategies:
            missing.append("h4.strategies")
    return missing


def loosens(old: SignalSettings, new: SignalSettings) -> bool:
    """True if `new` makes the worker act more readily or with less caution than `old`: publishing
    instead of only recording, a lower score bar (screen or AI), more coins, a lower liquidity
    floor, a wider stop, or more AI calls. Those need the password; anything else does not."""

    def below(old_v: Any, new_v: Any) -> bool:
        """The new value is lower than a value that was set before."""
        return old_v is not None and new_v is not None and new_v < old_v

    def above(old_v: Any, new_v: Any) -> bool:
        return old_v is not None and new_v is not None and new_v > old_v

    if new.mode == "PUBLISH" and old.mode != "PUBLISH":
        return True
    a, b = old.h4, new.h4
    if (
        below(a.min_score, b.min_score)
        or below(a.vol_mult, b.vol_mult)
        or below(a.range_mult, b.range_mult)
        or below(a.donchian_n, b.donchian_n)
        or (b.allow_short and not a.allow_short)
        or (a.enabled and bool(set(b.strategies) - set(a.strategies)))
    ):
        return True
    return (
        below(old.min_score_ratio, new.min_score_ratio)
        or below(old.ai_min_score, new.ai_min_score)
        or below(old.min_quote_volume_usdt, new.min_quote_volume_usdt)
        or new.top_n > old.top_n
        or above(old.atr_stop_multiple, new.atr_stop_multiple)
        or above(old.ai_max_calls, new.ai_max_calls)
    )


def _from_json(value: dict[str, Any]) -> SignalSettings:
    body = dict(value)
    try:
        return parse_settings(body)
    except SignalSettingsError:
        return SignalSettings()  # an unreadable row means "not configured", never a guess


def get_settings_row(session: Session) -> SignalConfigRow | None:
    return session.get(SignalConfigRow, 1)


def get_signal_settings(session: Session) -> SignalSettings:
    row = get_settings_row(session)
    return SignalSettings() if row is None else _from_json(row.value)


def set_signal_settings(
    session: Session, new: SignalSettings, *, by: str, now: datetime | None = None
) -> None:
    when = now or datetime.now(UTC)
    row = get_settings_row(session)
    before = None if row is None else row.value
    if row is None:
        session.add(SignalConfigRow(id=1, value=new.as_json(), updated_at=when, updated_by=by))
    else:
        row.value, row.updated_at, row.updated_by = new.as_json(), when, by
    AuditLogger(session).record(
        actor=by,
        action="signal_config.change",
        subject_type="setting",
        subject_id="signal_config",
        before=before,
        after=new.as_json(),
        at=when,
    )
    session.flush()


def request_run(session: Session, *, by: str, now: datetime | None = None) -> datetime:
    """Ask the worker for one pass now. The worker runs it at its next poll."""
    when = now or datetime.now(UTC)
    row = get_settings_row(session)
    if row is None:
        raise SignalSettingsError(["the worker has no settings yet"])
    row.run_requested_at = when
    AuditLogger(session).record(
        actor=by,
        action="signal_scan.requested",
        subject_type="setting",
        subject_id="signal_config",
        before=None,
        after={"requested_at": when.isoformat()},
        at=when,
    )
    session.flush()
    return when
