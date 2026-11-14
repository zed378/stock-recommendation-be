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
from aidss_trader.promotion import Promotion
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy

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
