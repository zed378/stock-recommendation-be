"""Risk Engine (ADR-009): the only gate between an intent and the exchange.

Two profiles:

* ENTRY runs every check. Anything uncertain fails it.
* EMERGENCY (stop, kill switch) runs only the checks that prevent a malformed or
  runaway order, never one that could keep a position open: a stop must not be
  refused because the daily-loss limit was hit.

The engine is a pure function of a `RiskContext` snapshot, so every check is
testable without a database or an exchange. `persist` records each check, passed
or not, so a refusal can always be explained afterwards (FR-T7).

A required limit that is unset fails the ENTRY profile (FR-T11). Nothing here has
a default threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from aidss_trader.config.limits import RiskLimits, unset_risk_fields
from aidss_trader.db.models import RiskCheckResult
from aidss_trader.intents.builder import Intent
from aidss_trader.market_data.pairs import PairRules, check_order

Profile = Literal["ENTRY", "EMERGENCY"]
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class RiskContext:
    now: datetime
    trading_state: str  # RUNNING | HALTED | CANCELLING | FLATTENING
    mode: str  # PAPER | APPROVAL | AUTO
    limits: RiskLimits | None
    rules: PairRules
    equity_idr: Decimal
    reference_price: Decimal  # best bid (BUY) or best ask (SELL) used to judge deviation
    market_data_age_s: float
    open_positions: int
    pair_exposure_idr: Decimal
    total_exposure_idr: Decimal
    daily_realised_loss_idr: Decimal  # positive number = loss since the day boundary
    drawdown_pct: Decimal
    consecutive_losses: int
    seconds_since_last_order: float | None
    orders_last_minute: int
    unknown_orders: int
    reconciliation_clean: bool
    clock_ok: bool
    permissions_ok: bool  # canWithdraw / canWithdrawFiat both false, can_trade true
    in_trading_window: bool = True
    has_position: bool = False  # for SELL: a position exists to sell


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    observed: str | None = None
    limit: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    approved: bool
    profile: Profile
    checks: list[CheckResult]

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _c(name: str, passed: bool, observed: object = None, limit: object = None) -> CheckResult:
    return CheckResult(
        name,
        passed,
        None if observed is None else str(observed),
        None if limit is None else str(limit),
    )


def evaluate(intent: Intent, ctx: RiskContext, profile: Profile) -> Decision:
    checks: list[CheckResult] = []
    add = checks.append

    # --- Checks that apply to every profile: the order must be well formed and safe to send.
    add(_c("permissions", ctx.permissions_ok))
    add(_c("clock", ctx.clock_ok))
    add(_c("pair_tradable", ctx.rules.tradable, ",".join(ctx.rules.blocked_reasons) or None))
    problems = check_order(ctx.rules, intent.entry_price, intent.quantity)
    add(_c("pair_minimums_and_increments", not problems, "; ".join(problems) or None))
    add(_c("positive_quantity", intent.quantity > 0, intent.quantity))
    add(_c("unknown_orders", ctx.unknown_orders == 0, ctx.unknown_orders, 0))

    if profile == "EMERGENCY":
        # A stop or flatten reduces risk. Refusing it for a loss limit would invert the point.
        add(_c("sells_only", intent.side == "SELL", intent.side, "SELL"))
        add(_c("has_position", ctx.has_position))
        return Decision(all(c.passed for c in checks), profile, checks)

    limits = ctx.limits
    missing = unset_risk_fields(limits)
    add(_c("limits_set", not missing, ",".join(missing) or None))
    add(_c("trading_state", ctx.trading_state == "RUNNING", ctx.trading_state, "RUNNING"))
    add(_c("reconciliation_clean", ctx.reconciliation_clean))
    add(_c("trading_window", ctx.in_trading_window))
    if missing or limits is None:
        return Decision(False, profile, checks)

    value = intent.quantity * intent.entry_price
    equity = ctx.equity_idr
    add(
        _c(
            "stop_present",
            intent.stop_price is not None and intent.stop_price < intent.entry_price
            if intent.side == "BUY"
            else True,
        )
    )
    add(
        _c(
            "market_data_fresh",
            ctx.market_data_age_s <= limits.freshness_limit_s,
            f"{ctx.market_data_age_s:.1f}s",
            f"{limits.freshness_limit_s}s",
        )
    )
    deviation = (
        abs(intent.entry_price - ctx.reference_price) / ctx.reference_price * 100
        if ctx.reference_price > 0
        else Decimal("Infinity")
    )
    add(
        _c(
            "price_deviation",
            deviation <= limits.price_deviation_pct,
            f"{deviation:.4f}%",
            f"{limits.price_deviation_pct}%",
        )
    )
    add(_c("order_value", value <= limits.max_order_idr, value, limits.max_order_idr))
    if intent.side == "BUY":
        add(
            _c(
                "open_positions",
                ctx.open_positions < limits.max_open_positions,
                ctx.open_positions,
                limits.max_open_positions,
            )
        )
        pair_pct = (
            (ctx.pair_exposure_idr + value) / equity * 100 if equity > 0 else Decimal("Infinity")
        )
        add(
            _c(
                "pair_exposure",
                pair_pct <= limits.max_exposure_per_pair_pct,
                f"{pair_pct:.2f}%",
                f"{limits.max_exposure_per_pair_pct}%",
            )
        )
        total_pct = (
            (ctx.total_exposure_idr + value) / equity * 100 if equity > 0 else Decimal("Infinity")
        )
        add(
            _c(
                "total_exposure",
                total_pct <= limits.max_total_exposure_pct,
                f"{total_pct:.2f}%",
                f"{limits.max_total_exposure_pct}%",
            )
        )
        risk_pct = (
            (intent.risk_amount_idr or ZERO) / equity * 100 if equity > 0 else Decimal("Infinity")
        )
        add(
            _c(
                "risk_per_trade",
                risk_pct <= limits.risk_per_trade_pct,
                f"{risk_pct:.4f}%",
                f"{limits.risk_per_trade_pct}%",
            )
        )
        add(
            _c(
                "daily_loss",
                ctx.daily_realised_loss_idr < limits.max_daily_loss_idr,
                ctx.daily_realised_loss_idr,
                limits.max_daily_loss_idr,
            )
        )
        add(
            _c(
                "drawdown",
                ctx.drawdown_pct < limits.max_drawdown_pct,
                f"{ctx.drawdown_pct:.2f}%",
                f"{limits.max_drawdown_pct}%",
            )
        )
        add(
            _c(
                "consecutive_losses",
                ctx.consecutive_losses < limits.max_consecutive_losses,
                ctx.consecutive_losses,
                limits.max_consecutive_losses,
            )
        )
        add(
            _c(
                "cooldown",
                ctx.seconds_since_last_order is None
                or ctx.seconds_since_last_order >= limits.cooldown_s,
                ctx.seconds_since_last_order,
                limits.cooldown_s,
            )
        )
    else:
        add(_c("has_position", ctx.has_position))
    add(
        _c(
            "order_rate",
            ctx.orders_last_minute < limits.order_rate_limit,
            ctx.orders_last_minute,
            limits.order_rate_limit,
        )
    )
    return Decision(all(c.passed for c in checks), profile, checks)


def persist(
    session: Session, intent: Intent, decision: Decision, now: datetime | None = None
) -> None:
    at = now or datetime.now(UTC)
    for c in decision.checks:
        session.add(
            RiskCheckResult(
                intent_identity=intent.identity,
                profile=decision.profile,
                check=c.name,
                passed=c.passed,
                observed=c.observed,
                limit=c.limit,
                at=at,
            )
        )
    session.flush()


# --------------------------------------------------------------------- breakers


@dataclass(frozen=True, slots=True)
class Breaker:
    name: str
    tier: Literal["HALT", "CANCEL"]  # never FLATTEN (ADR-036)
    observed: str
    limit: str


def breakers(ctx: RiskContext) -> list[Breaker]:
    """Conditions that stop trading by themselves. They halt or cancel; they never sell."""
    out: list[Breaker] = []
    limits = ctx.limits
    if not ctx.permissions_ok:
        out.append(Breaker("permissions", "HALT", "withdraw or no trade", "none allowed"))
    if not ctx.clock_ok:
        out.append(Breaker("clock_skew", "HALT", "beyond recvWindow", "within"))
    if ctx.unknown_orders:
        out.append(Breaker("unknown_order", "HALT", str(ctx.unknown_orders), "0"))
    if not ctx.reconciliation_clean:
        out.append(Breaker("reconciliation_difference", "HALT", "difference", "none"))
    if limits is not None:
        if (
            limits.max_daily_loss_idr is not None
            and ctx.daily_realised_loss_idr >= limits.max_daily_loss_idr
        ):
            out.append(
                Breaker(
                    "daily_loss",
                    "CANCEL",
                    str(ctx.daily_realised_loss_idr),
                    str(limits.max_daily_loss_idr),
                )
            )
        if limits.max_drawdown_pct is not None and ctx.drawdown_pct >= limits.max_drawdown_pct:
            out.append(
                Breaker("drawdown", "CANCEL", str(ctx.drawdown_pct), str(limits.max_drawdown_pct))
            )
        if (
            limits.max_consecutive_losses is not None
            and ctx.consecutive_losses >= limits.max_consecutive_losses
        ):
            out.append(
                Breaker(
                    "consecutive_losses",
                    "CANCEL",
                    str(ctx.consecutive_losses),
                    str(limits.max_consecutive_losses),
                )
            )
        if (
            limits.freshness_limit_s is not None
            and ctx.market_data_age_s > limits.freshness_limit_s
        ):
            out.append(
                Breaker(
                    "stale_data",
                    "HALT",
                    f"{ctx.market_data_age_s:.0f}s",
                    f"{limits.freshness_limit_s}s",
                )
            )
    return out
