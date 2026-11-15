"""Owner-set operational settings: allowlist, liquidity filter, strategy parameters.

Nothing here has a default that lets a pair or a strategy run. Until the owner has set
the allowlist, the liquidity filter (OQ-8), and the strategy parameters (OQ-11), the
runtime evaluates nothing and sends nothing. Every change is audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.db.models import TraderSetting
from aidss_trader.paper import CostModel, PaperConfig
from aidss_trader.promotion import Promotion, Thresholds
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy

PAPER_KEY = "paper_config"
THRESHOLDS_KEY = "promotion_thresholds"
THRESHOLD_FIELDS: tuple[str, ...] = (
    "min_paper_trades",
    "max_paper_drawdown_pct",
    "backtest_min_return_pct",
    "max_live_capital_idr",
    "max_slippage_pct",
)
# Candles the runtime keeps per pair. A strategy that needs more history than this could never
# evaluate, so the parameter API refuses it instead of letting it sit silently inert.
MAX_HISTORY_BARS = 300
ALLOWLIST_KEY = "allowlist"
STRATEGY_PREFIX = "strategy_params:"


@dataclass(frozen=True, slots=True)
class LiquidityFilter:
    """The owner's numbers (OQ-8). A pair is inactive unless both are set."""

    min_quote_volume_24h_idr: Decimal | None = None
    max_spread_pct: Decimal | None = None

    @property
    def configured(self) -> bool:
        return self.min_quote_volume_24h_idr is not None and self.max_spread_pct is not None


@dataclass(frozen=True, slots=True)
class Allowlist:
    pairs: tuple[str, ...] = ()
    liquidity: LiquidityFilter = LiquidityFilter()


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def get_allowlist(session: Session) -> Allowlist:
    row = session.get(TraderSetting, ALLOWLIST_KEY)
    if row is None:
        return Allowlist()
    v = row.value
    return Allowlist(
        pairs=tuple(str(p).upper() for p in v.get("pairs", [])),
        liquidity=LiquidityFilter(
            _dec(v.get("min_quote_volume_24h_idr")), _dec(v.get("max_spread_pct"))
        ),
    )


def _put(session: Session, key: str, value: dict[str, Any], by: str, now: datetime) -> None:
    row = session.get(TraderSetting, key)
    before = None if row is None else row.value
    if row is None:
        session.add(TraderSetting(key=key, value=value, updated_at=now, updated_by=by))
    else:
        row.value, row.updated_at, row.updated_by = value, now, by
    AuditLogger(session).record(
        actor=by,
        action="setting.change",
        subject_type="setting",
        subject_id=key,
        before=before,
        after=value,
        at=now,
    )
    session.flush()


def set_allowlist(
    session: Session, allowlist: Allowlist, *, by: str, now: datetime | None = None
) -> None:
    _put(
        session,
        ALLOWLIST_KEY,
        {
            "pairs": [p.upper() for p in allowlist.pairs],
            "min_quote_volume_24h_idr": _text(allowlist.liquidity.min_quote_volume_24h_idr),
            "max_spread_pct": _text(allowlist.liquidity.max_spread_pct),
        },
        by,
        now or datetime.now(UTC),
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def set_strategy_params(
    session: Session,
    strategy_id: str,
    params: EmaAdxParams,
    *,
    by: str,
    now: datetime | None = None,
) -> str:
    """Store parameters, register the resulting version, and return it.

    A parameter change is a new version and a new version starts in PAPER (ADR-020).
    """
    now = now or datetime.now(UTC)
    strategy = EmaAdxStrategy(params)
    _put(
        session,
        STRATEGY_PREFIX + strategy_id,
        {
            "ema_fast": params.ema_fast,
            "ema_slow": params.ema_slow,
            "adx_period": params.adx_period,
            "adx_threshold": _text(params.adx_threshold),
            "atr_period": params.atr_period,
            "atr_stop_multiple": _text(params.atr_stop_multiple),
            "cooldown_s": params.cooldown_s,
        },
        by,
        now,
    )
    Promotion(session, now=lambda: now).register(strategy_id, strategy.version_id())
    return strategy.version_id()


def load_strategy(session: Session, strategy_id: str = "ema_adx") -> EmaAdxStrategy | None:
    """The configured strategy, or None when unset or invalid. Never a guessed one."""
    row = session.get(TraderSetting, STRATEGY_PREFIX + strategy_id)
    if row is None:
        return None
    v = row.value
    try:
        return EmaAdxStrategy(
            EmaAdxParams(
                ema_fast=int(v["ema_fast"]),
                ema_slow=int(v["ema_slow"]),
                adx_period=int(v["adx_period"]),
                adx_threshold=Decimal(str(v["adx_threshold"])),
                atr_period=int(v["atr_period"]),
                atr_stop_multiple=Decimal(str(v["atr_stop_multiple"])),
                cooldown_s=int(v["cooldown_s"]),
            )
        )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


@dataclass(frozen=True, slots=True)
class PaperSettings:
    """The owner's paper-trading numbers (OQ-5): costs, slippage, partial fills, start capital.

    Nothing has a default. Until all of them are set the paper simulation does not run, so a
    paper result can never come from a number nobody chose.
    """

    config: PaperConfig
    start_equity_idr: Decimal


_PAPER_FIELDS = (
    "slippage_pct",
    "partial_fill_fraction",
    "maker_fee_pct",
    "taker_fee_pct",
    "tax_pct",
    "clearing_pct",
    "start_equity_idr",
)


def get_paper_settings(session: Session) -> PaperSettings | None:
    row = session.get(TraderSetting, PAPER_KEY)
    if row is None:
        return None
    v = row.value
    try:
        nums = {name: Decimal(str(v[name])) for name in _PAPER_FIELDS}
        if nums["start_equity_idr"] <= 0:
            return None
        return PaperSettings(
            PaperConfig(
                slippage_pct=nums["slippage_pct"],
                partial_fill_fraction=nums["partial_fill_fraction"],
                costs=CostModel(
                    nums["maker_fee_pct"],
                    nums["taker_fee_pct"],
                    nums["tax_pct"],
                    nums["clearing_pct"],
                ),
            ),
            nums["start_equity_idr"],
        )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None  # unset or invalid: the simulation does not run


def set_paper_settings(
    session: Session, values: dict[str, Decimal], *, by: str, now: datetime | None = None
) -> None:
    missing = [n for n in _PAPER_FIELDS if n not in values]
    if missing:
        raise ValueError(f"paper settings need every value: missing {missing}")
    PaperConfig(  # validates ranges
        slippage_pct=values["slippage_pct"],
        partial_fill_fraction=values["partial_fill_fraction"],
        costs=CostModel(
            values["maker_fee_pct"],
            values["taker_fee_pct"],
            values["tax_pct"],
            values["clearing_pct"],
        ),
    )
    if values["start_equity_idr"] <= 0:
        raise ValueError("start_equity_idr must be positive")
    for name in ("maker_fee_pct", "taker_fee_pct", "tax_pct", "clearing_pct", "slippage_pct"):
        if not 0 <= values[name] <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
    _put(
        session,
        PAPER_KEY,
        {n: _text(values[n]) for n in _PAPER_FIELDS},
        by,
        now or datetime.now(UTC),
    )


def get_strategy_params(session: Session, strategy_id: str) -> dict[str, str] | None:
    """The stored parameters as plain strings for display, or None when never set."""
    row = session.get(TraderSetting, STRATEGY_PREFIX + strategy_id)
    if row is None:
        return None
    return {k: ("" if v is None else str(v)) for k, v in row.value.items()}


def paper_flatters(old: PaperSettings, new: PaperSettings) -> bool:
    """True if `new` makes simulated results look better than `old`: lower costs or slippage,
    or more of each order filled. Starting capital is not a flattery, it only scales the book."""
    a, b = old.config, new.config
    return (
        b.slippage_pct < a.slippage_pct
        or b.partial_fill_fraction > a.partial_fill_fraction
        or b.costs.maker_fee_pct < a.costs.maker_fee_pct
        or b.costs.taker_fee_pct < a.costs.taker_fee_pct
        or b.costs.tax_pct < a.costs.tax_pct
        or b.costs.clearing_pct < a.costs.clearing_pct
    )


def threshold_problem(name: str, value: Any) -> str | None:
    """Why a promotion threshold value is not acceptable, or None. `None` (unset) is always
    acceptable: it blocks the corresponding promotion gate (`docs/05-MODULE-SPECIFICATIONS/11`)."""
    if value is None:
        return None
    if name == "min_paper_trades":
        ok = isinstance(value, int) and value >= 1
        return None if ok else "must be a whole number of at least 1"
    if name == "max_paper_drawdown_pct":
        return None if 0 < value <= 100 else "must be above 0 and at most 100"
    if name == "backtest_min_return_pct":
        return None if value > -100 else "must be above -100"
    if name == "max_live_capital_idr":
        return None if value > 0 else "must be above 0"
    if name == "max_slippage_pct":
        return None if 0 <= value <= 100 else "must be between 0 and 100"
    return None


def get_promotion_thresholds(session: Session) -> Thresholds:
    """Load stored owner promotion thresholds (OQ-12). Any unset or invalid field stays None
    and blocks the gate that depends on it."""
    row = session.get(TraderSetting, THRESHOLDS_KEY)
    if row is None or not isinstance(row.value, dict):
        return Thresholds()
    raw = row.value

    def _int_or_none(k: str) -> int | None:
        v = raw.get(k)
        if v is None or v == "":
            return None
        try:
            parsed = int(str(v))
            return parsed if threshold_problem(k, parsed) is None else None
        except (TypeError, ValueError):
            return None

    def _dec_or_none(k: str) -> Decimal | None:
        v = raw.get(k)
        if v is None or v == "":
            return None
        try:
            parsed = _dec(v)
            return parsed if threshold_problem(k, parsed) is None else None
        except (TypeError, ValueError, InvalidOperation):
            return None

    return Thresholds(
        min_paper_trades=_int_or_none("min_paper_trades"),
        max_paper_drawdown_pct=_dec_or_none("max_paper_drawdown_pct"),
        backtest_min_return_pct=_dec_or_none("backtest_min_return_pct"),
        max_live_capital_idr=_dec_or_none("max_live_capital_idr"),
        max_slippage_pct=_dec_or_none("max_slippage_pct"),
    )


def set_promotion_thresholds(
    session: Session,
    thresholds: Thresholds,
    *,
    by: str,
    now: datetime | None = None,
) -> None:
    """Validate and persist owner promotion thresholds (OQ-12), writing an audit entry."""
    for name in THRESHOLD_FIELDS:
        val = getattr(thresholds, name)
        prob = threshold_problem(name, val)
        if prob is not None:
            raise ValueError(f"{name}: {prob}")
    payload: dict[str, str | int | None] = {
        "min_paper_trades": thresholds.min_paper_trades,
        "max_paper_drawdown_pct": (
            None
            if thresholds.max_paper_drawdown_pct is None
            else _text(thresholds.max_paper_drawdown_pct)
        ),
        "backtest_min_return_pct": (
            None
            if thresholds.backtest_min_return_pct is None
            else _text(thresholds.backtest_min_return_pct)
        ),
        "max_live_capital_idr": (
            None
            if thresholds.max_live_capital_idr is None
            else _text(thresholds.max_live_capital_idr)
        ),
        "max_slippage_pct": (
            None if thresholds.max_slippage_pct is None else _text(thresholds.max_slippage_pct)
        ),
    }
    _put(session, THRESHOLDS_KEY, payload, by, now or datetime.now(UTC))


_THRESHOLD_HIGHER_IS_LOOSER = (
    "max_paper_drawdown_pct",
    "max_live_capital_idr",
    "max_slippage_pct",
)
_THRESHOLD_LOWER_IS_LOOSER = (
    "min_paper_trades",
    "backtest_min_return_pct",
)


def thresholds_loosen(old: Thresholds, new: Thresholds) -> bool:
    """True if `new` makes promotion easier than `old`. Setting a threshold where none was set
    also counts as loosening because it unblocks a gate that previously refused promotion."""
    for name in _THRESHOLD_HIGHER_IS_LOOSER + _THRESHOLD_LOWER_IS_LOOSER:
        a, b = getattr(old, name), getattr(new, name)
        if b is None:
            continue  # unsetting blocks the gate: tighter
        if a is None:
            return True
        if (b > a) if name in _THRESHOLD_HIGHER_IS_LOOSER else (b < a):
            return True
    return False

