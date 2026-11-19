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

from sqlalchemy import select
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
PAIR_GROUPS_KEY = "pair_groups"
#: Ceiling on how many pairs "ALL" may ask the exchange's public endpoints to keep current. Each
#: active pair costs a candle request every few minutes and the public legacy API is rate limited,
#: so the owner chooses N (it is never defaulted) and this only bounds a typo.
MAX_ALL_PAIRS_LIMIT = 200
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
    """`pairs` are the ones the owner chose by name. `all_pairs` adds every IDR market that passes
    the liquidity filter, best 24 hour volume first, at most `max_pairs` of them: ALL is inactive
    until the owner sets N."""

    pairs: tuple[str, ...] = ()
    liquidity: LiquidityFilter = LiquidityFilter()
    all_pairs: bool = False
    max_pairs: int | None = None

    @property
    def all_active(self) -> bool:
        return self.all_pairs and self.max_pairs is not None and self.liquidity.configured

    @property
    def has_scope(self) -> bool:
        """Something is selected: named pairs, or ALL with its number set."""
        return bool(self.pairs) or self.all_active


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
        all_pairs=bool(v.get("all_pairs", False)),
        max_pairs=_int(v.get("max_pairs")),
    )


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


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
            "all_pairs": allowlist.all_pairs,
            "max_pairs": allowlist.max_pairs,
        },
        by,
        now or datetime.now(UTC),
    )


def get_pair_groups(session: Session) -> dict[str, tuple[str, ...]]:
    """The owner's named groups of pairs. A group is a shortcut for ticking several pairs at once:
    it names pairs, it never trades anything by itself (selecting it copies its pairs into the
    allowlist when that is saved)."""
    row = session.get(TraderSetting, PAIR_GROUPS_KEY)
    if row is None:
        return {}
    groups = row.value.get("groups", {})
    return {str(name): tuple(str(p).upper() for p in pairs) for name, pairs in groups.items()}


def set_pair_groups(
    session: Session,
    groups: dict[str, tuple[str, ...]],
    *,
    by: str,
    now: datetime | None = None,
) -> None:
    _put(
        session,
        PAIR_GROUPS_KEY,
        {"groups": {name: [p.upper() for p in pairs] for name, pairs in sorted(groups.items())}},
        by,
        now or datetime.now(UTC),
    )


STRATEGY_DEF_PREFIX = "strategy_def:"


@dataclass(frozen=True, slots=True)
class StrategyDef:
    """A strategy the owner defined: a kind and its parameters, as data (see `strategy.kinds`).

    `legacy` marks the reference strategy, which keeps its original storage
    (`strategy_params:ema_adx`) so everything that already reads it keeps working.
    """

    id: str
    kind: str
    label: str
    params: dict[str, str]
    legacy: bool = False


def _plain(params: dict[str, Any]) -> dict[str, str]:
    return {str(k): ("" if v is None else str(v)) for k, v in params.items()}


def list_strategy_defs(session: Session) -> list[StrategyDef]:
    out: list[StrategyDef] = []
    for row in session.scalars(select(TraderSetting).order_by(TraderSetting.key)):
        if row.value.get("deleted") is True:
            continue  # a removed definition (see `delete_strategy_def`)
        if row.key.startswith(STRATEGY_PREFIX):
            sid = row.key[len(STRATEGY_PREFIX) :]
            out.append(StrategyDef(sid, "ema_adx", sid, _plain(row.value), legacy=True))
        elif row.key.startswith(STRATEGY_DEF_PREFIX):
            sid = row.key[len(STRATEGY_DEF_PREFIX) :]
            v = row.value
            out.append(
                StrategyDef(
                    sid,
                    str(v.get("kind", "")),
                    str(v.get("label", sid)),
                    _plain(v.get("params", {})),
                )
            )
    return sorted(out, key=lambda d: (not d.legacy, d.id))


def get_strategy_def(session: Session, strategy_id: str) -> StrategyDef | None:
    return next((d for d in list_strategy_defs(session) if d.id == strategy_id), None)


def set_strategy_def(
    session: Session, d: StrategyDef, *, by: str, now: datetime | None = None
) -> None:
    """Create or replace a user-built strategy. The reference strategy is set through
    `set_strategy_params`, which also registers its version and returns it to PAPER."""
    if d.legacy:
        raise ValueError("the reference strategy is set through set_strategy_params")
    _put(
        session,
        STRATEGY_DEF_PREFIX + d.id,
        {"kind": d.kind, "label": d.label, "params": dict(d.params)},
        by,
        now or datetime.now(UTC),
    )


def delete_strategy_def(
    session: Session, strategy_id: str, *, by: str, now: datetime | None = None
) -> bool:
    """Remove a definition, wherever it is stored. Backtest rows and every audit entry stay.

    The row is replaced by a tombstone, never deleted: `trader_rw` has no DELETE on
    `trader_setting` (it is not meant to), and the audit entry keeps the old value. Every reader
    treats a tombstone as "not defined", and the id can be created again later.
    """
    existing = get_strategy_def(session, strategy_id)
    if existing is None:
        return False
    key = (STRATEGY_PREFIX if existing.legacy else STRATEGY_DEF_PREFIX) + strategy_id
    row = session.get(TraderSetting, key)
    assert row is not None
    when = now or datetime.now(UTC)
    before = row.value
    row.value, row.updated_at, row.updated_by = {"deleted": True}, when, by
    flag = session.get(TraderSetting, STRATEGY_ENABLED_PREFIX + strategy_id)
    if flag is not None:
        flag.value, flag.updated_at, flag.updated_by = {"enabled": False}, when, by
    AuditLogger(session).record(
        actor=by,
        action="setting.delete",
        subject_type="setting",
        subject_id=key,
        before=before,
        after={"deleted": True},
        at=when,
    )
    session.flush()
    return True


STRATEGY_ENABLED_PREFIX = "strategy_enabled:"
#: A resource limit, not a loss limit (ADR-062): every enabled strategy is evaluated on every
#: active pair each cycle.
MAX_ENABLED_STRATEGIES = 8


def enabled_strategy_ids(session: Session) -> list[str]:
    """Strategies the owner has switched on in the paper loop, in the order they are evaluated
    (ascending id, which is also how a same-candle collision is settled)."""
    out = [
        row.key[len(STRATEGY_ENABLED_PREFIX) :]
        for row in session.scalars(
            select(TraderSetting).where(TraderSetting.key.startswith(STRATEGY_ENABLED_PREFIX))
        )
        if row.value.get("enabled") is True
    ]
    return sorted(out)


def set_strategy_enabled(
    session: Session, strategy_id: str, enabled: bool, *, by: str, now: datetime | None = None
) -> None:
    _put(
        session,
        STRATEGY_ENABLED_PREFIX + strategy_id,
        {"enabled": enabled},
        by,
        now or datetime.now(UTC),
    )


def duplicate_strategy_def(
    session: Session, kind: str, params: dict[str, str], *, exclude: str | None = None
) -> str | None:
    """The id of another definition with the same kind and the same numbers, if there is one.

    Two such definitions would build identical versions and identical intent identities, so one
    would silently shadow the other (ADR-062). Parameters that do not build are never duplicates.
    """
    from aidss_trader.strategy.kinds import ParameterError, build_strategy

    try:
        version = build_strategy(kind, params).version_id()
    except ParameterError:
        return None
    for d in list_strategy_defs(session):
        if d.id == exclude:
            continue
        try:
            if build_strategy(d.kind, d.params).version_id() == version:
                return d.id
        except ParameterError:
            continue
    return None


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
    if row is None or row.value.get("deleted") is True:
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
    if row is None or row.value.get("deleted") is True:
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

