"""Mode promotion (docs/05-MODULE-SPECIFICATIONS/11, ADR-003, ADR-020).

Every threshold is the owner's (OQ-12, OQ-16) except "at least four weeks" (ADR-020).
**An unset threshold blocks promotion; there is no override.** The thresholds are meant
to be set before the evidence exists, so they cannot be chosen after seeing a result.

What is computed from stored data here: time in the current mode, completed paper
trades, unresolved reconciliation differences, breaker and kill-switch events in the
period. Backtest results, paper drawdown, slippage versus paper, and the owner's
denial fraction need evidence the platform does not store yet, so they are supplied
by the caller and recorded as supplied.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss_trader.audit import AuditLogger
from aidss_trader.backtest.evidence import backtest_evidence
from aidss_trader.db.models import (
    BreakerEvent,
    Fill,
    KillSwitchEvent,
    ModeChange,
    ReconciliationDifference,
    StrategyRow,
)
from aidss_trader.notify import Notifier

MODES = ("PAPER", "APPROVAL", "AUTO")
MIN_DURATION = timedelta(weeks=4)  # ADR-020: the one decided number


class PromotionRefused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("promotion refused: " + "; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class Thresholds:
    """All owner numbers. None means unset and blocks the gate that needs it."""

    min_paper_trades: int | None = None
    max_paper_drawdown_pct: Decimal | None = None
    backtest_min_return_pct: Decimal | None = None
    max_live_capital_idr: Decimal | None = None
    max_slippage_pct: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SuppliedEvidence:
    backtest_return_pct: Decimal | None = None
    paper_drawdown_pct: Decimal | None = None
    live_capital_used_idr: Decimal | None = None
    slippage_vs_paper_pct: Decimal | None = None
    denial_fraction: Decimal | None = None  # reviewed by the owner, not gated


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    measured: str | None
    threshold: str | None
    passed: bool
    reason: str = ""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v


def _gate(name: str, measured: Any, threshold: Any, ok: Callable[[], bool]) -> Gate:
    if threshold is None:
        return Gate(
            name,
            None if measured is None else str(measured),
            None,
            False,
            "threshold unset (owner)",
        )
    if measured is None:
        return Gate(name, None, str(threshold), False, "no evidence")
    return Gate(name, str(measured), str(threshold), bool(ok()))


class Promotion:
    def __init__(
        self,
        session: Session,
        notifier: Notifier | None = None,
        *,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._s, self._notifier, self._now = session, notifier, now
        self._audit = AuditLogger(session)

    def register(self, strategy_id: str, version: str) -> StrategyRow:
        row = self._s.get(StrategyRow, strategy_id)
        if row is None:
            row = StrategyRow(
                strategy_id=strategy_id, version=version, mode="PAPER", since=self._now()
            )
            self._s.add(row)
        elif row.version != version:
            # A new version always starts again in PAPER (ADR-020).
            self._record(row, "PAPER", "system", None, f"new version {version}")
            row.version, row.mode, row.since = version, "PAPER", self._now()
        self._s.commit()
        return row

    def gates(
        self, strategy_id: str, to_mode: str, thresholds: Thresholds, supplied: SuppliedEvidence
    ) -> list[Gate]:
        row = self._s.get(StrategyRow, strategy_id)
        if row is None:
            raise PromotionRefused(["unknown strategy"])
        since, now = _aware(row.since), self._now()
        running = now - since
        days = f"{running.total_seconds() / 86400:.1f} days"
        out = [Gate("duration", days, f"{MIN_DURATION.days} days", running >= MIN_DURATION)]
        diffs = (
            self._s.scalar(
                select(func.count())
                .select_from(ReconciliationDifference)
                .where(ReconciliationDifference.resolved_at.is_(None))
            )
            or 0
        )
        out.append(Gate("data_integrity", str(diffs), "0", diffs == 0))
        if to_mode == "APPROVAL":
            trades = (
                self._s.scalar(
                    select(func.count())
                    .select_from(Fill)
                    .where(Fill.origin == "PAPER", Fill.side == "SELL", Fill.executed_at >= since)
                )
                or 0
            )
            # Read from the stored BACKTEST runs, never from a figure typed in: see
            # `backtest.evidence` (ADR-059). `supplied.backtest_return_pct` is ignored.
            evidence = backtest_evidence(self._s, strategy_id, row.version)
            bt_return = None if evidence is None else evidence.return_pct
            out += [
                _gate(
                    "backtest",
                    None if evidence is None else evidence.describe(),
                    thresholds.backtest_min_return_pct,
                    lambda: bt_return >= thresholds.backtest_min_return_pct,
                ),
                _gate(
                    "paper_activity",
                    trades,
                    thresholds.min_paper_trades,
                    lambda: trades >= thresholds.min_paper_trades,
                ),
                _gate(
                    "paper_drawdown",
                    supplied.paper_drawdown_pct,
                    thresholds.max_paper_drawdown_pct,
                    lambda: supplied.paper_drawdown_pct <= thresholds.max_paper_drawdown_pct,
                ),
            ]
        elif to_mode == "AUTO":
            breakers = (
                self._s.scalar(
                    select(func.count())
                    .select_from(BreakerEvent)
                    .where(BreakerEvent.tripped_at >= since)
                )
                or 0
            )
            kills = (
                self._s.scalar(
                    select(func.count())
                    .select_from(KillSwitchEvent)
                    .where(KillSwitchEvent.started_at >= since)
                )
                or 0
            )
            out += [
                Gate(
                    "no_breaker_or_kill_switch", f"{breakers + kills}", "0", breakers + kills == 0
                ),
                _gate(
                    "capital",
                    supplied.live_capital_used_idr,
                    thresholds.max_live_capital_idr,
                    lambda: supplied.live_capital_used_idr <= thresholds.max_live_capital_idr,
                ),
                _gate(
                    "slippage",
                    supplied.slippage_vs_paper_pct,
                    thresholds.max_slippage_pct,
                    lambda: supplied.slippage_vs_paper_pct <= thresholds.max_slippage_pct,
                ),
            ]
        return out

    def promote(
        self,
        strategy_id: str,
        actor: str,
        thresholds: Thresholds,
        supplied: SuppliedEvidence,
        note: str | None = None,
        *,
        step_up_ok: bool = False,
    ) -> StrategyRow:
        if not actor or actor.lower().startswith(("system", "strategy", "job", "service")):
            raise PromotionRefused(["only a named human may promote"])
        row = self._s.get(StrategyRow, strategy_id)
        if row is None:
            raise PromotionRefused(["unknown strategy"])
        idx = MODES.index(row.mode)
        if idx == len(MODES) - 1:
            raise PromotionRefused(["already in the highest mode"])
        target = MODES[idx + 1]  # one step at a time; PAPER cannot jump to AUTO
        if target == "AUTO" and not step_up_ok:
            raise PromotionRefused(["promotion to AUTO needs a step-up grant"])
        gates = self.gates(strategy_id, target, thresholds, supplied)
        bad = [f"{g.name}: {g.reason or 'failed'}" for g in gates if not g.passed]
        if bad:
            raise PromotionRefused(bad)
        evidence = {
            "gates": [asdict(g) for g in gates],
            "supplied": {
                f.name: (
                    None if getattr(supplied, f.name) is None else str(getattr(supplied, f.name))
                )
                for f in fields(supplied)
            },
        }
        self._record(row, target, actor, evidence, note)
        row.mode, row.since = target, self._now()
        self._finish(row, actor, note)
        return row

    def demote(
        self, strategy_id: str, actor: str, to_mode: str, note: str | None = None
    ) -> StrategyRow:
        row = self._s.get(StrategyRow, strategy_id)
        if row is None:
            raise PromotionRefused(["unknown strategy"])
        if to_mode not in MODES or MODES.index(to_mode) >= MODES.index(row.mode):
            raise PromotionRefused(["demotion must go to a lower mode"])
        self._record(row, to_mode, actor, None, note)  # no evidence needed, always allowed
        row.mode, row.since = to_mode, self._now()
        self._finish(row, actor, note)
        return row

    def _record(
        self,
        row: StrategyRow,
        to_mode: str,
        actor: str,
        evidence: dict[str, Any] | None,
        note: str | None,
    ) -> None:
        self._s.add(
            ModeChange(
                strategy_id=row.strategy_id,
                from_mode=row.mode,
                to_mode=to_mode,
                at=self._now(),
                by=actor,
                evidence=evidence,
                note=(note or "")[:200] or None,
            )
        )

    def _finish(self, row: StrategyRow, actor: str, note: str | None) -> None:
        self._audit.record(
            actor=actor,
            action="strategy.mode_changed",
            subject_type="strategy",
            subject_id=row.strategy_id,
            after={"mode": row.mode, "note": note},
        )
        self._s.commit()
        if self._notifier:
            self._notifier.emit(
                "mode_changed",
                f"{row.strategy_id} is now {row.mode}",
                {"strategy": row.strategy_id, "mode": row.mode},
            )
