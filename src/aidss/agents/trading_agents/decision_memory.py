"""Decision memory, look-ahead-safe settlement, and post-decision reflection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.base import Agent, AgentRunner
from aidss.agents.context import AnalysisContext
from aidss.db.models import Asset, HistoricalPrice, TradingDecisionLog
from aidss.domain.types import RecommendationLabel
from aidss.llm.router import TaskComplexity
from aidss.prompts.schemas import DecisionReflectionOutput


class DecisionReflector(Agent):
    name = "decision_reflector"
    template_name = "decision_reflection"
    output_model = DecisionReflectionOutput
    complexity = TaskComplexity.LIGHT

    def __init__(self, decision: TradingDecisionLog) -> None:
        self._decision = decision

    def prompt_context(self, context: AnalysisContext) -> dict[str, Any]:
        return {
            "ticker": self._decision.ticker,
            "exchange": self._decision.exchange,
            "trade_date": self._decision.trade_date.date().isoformat(),
            "final_rating": self._decision.final_rating.value,
            "confidence": self._decision.confidence,
            "entry_price": str(self._decision.entry_price or "unknown"),
            "settled_price": str(self._decision.settled_price or "unknown"),
            "realized_return_pct": (
                round(self._decision.realized_return_pct, 2)
                if self._decision.realized_return_pct is not None
                else 0.0
            ),
            "outcome_label": self._decision.outcome_label or "neutral",
            "decision_summary": self._decision.portfolio_decision,
            "investment_plan": self._decision.investment_plan,
        }


def load_past_lessons(
    session: Session,
    asset_id: uuid.UUID,
    ticker: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Load settled past decisions and reflection lessons for Portfolio Manager."""
    same_ticker = session.scalars(
        select(TradingDecisionLog)
        .where(
            TradingDecisionLog.asset_id == asset_id,
            TradingDecisionLog.settled_at.is_not(None),
        )
        .order_by(TradingDecisionLog.settled_at.desc())
        .limit(limit)
    ).all()

    lessons: list[dict[str, Any]] = []
    for row in same_ticker:
        lessons.append(
            {
                "scope": "same_ticker",
                "ticker": row.ticker,
                "trade_date": row.trade_date.date().isoformat(),
                "final_rating": row.final_rating.value,
                "realized_return_pct": row.realized_return_pct,
                "outcome_label": row.outcome_label,
                "lesson": row.reflection_lesson or "",
            }
        )

    if len(lessons) < limit:
        cross_ticker = session.scalars(
            select(TradingDecisionLog)
            .where(
                TradingDecisionLog.ticker != ticker,
                TradingDecisionLog.settled_at.is_not(None),
                TradingDecisionLog.reflection_lesson.is_not(None),
            )
            .order_by(TradingDecisionLog.settled_at.desc())
            .limit(limit - len(lessons))
        ).all()
        for row in cross_ticker:
            lessons.append(
                {
                    "scope": "cross_ticker",
                    "ticker": row.ticker,
                    "trade_date": row.trade_date.date().isoformat(),
                    "final_rating": row.final_rating.value,
                    "realized_return_pct": row.realized_return_pct,
                    "outcome_label": row.outcome_label,
                    "lesson": row.reflection_lesson or "",
                }
            )

    return lessons


def record_decision(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    asset: Asset,
    analysis_result_id: uuid.UUID | None,
    final_rating: RecommendationLabel,
    confidence: float,
    entry_price: Decimal | None,
    investment_plan: str,
    trader_proposal: str,
    portfolio_decision: str,
    debate_trace: dict[str, Any],
    trade_date: datetime | None = None,
) -> TradingDecisionLog:
    """Persist a TradingAgents decision log row."""
    row = TradingDecisionLog(
        user_id=user_id,
        asset_id=asset.id,
        analysis_result_id=analysis_result_id,
        ticker=asset.ticker,
        exchange=asset.exchange,
        trade_date=trade_date or datetime.now(UTC),
        final_rating=final_rating,
        confidence=confidence,
        entry_price=entry_price,
        investment_plan=investment_plan,
        trader_proposal=trader_proposal,
        portfolio_decision=portfolio_decision,
        debate_trace=debate_trace,
    )
    session.add(row)
    session.flush()
    return row


def _score_outcome(rating: RecommendationLabel, return_pct: float) -> str:
    """Evaluate directional alignment without look-ahead."""
    direction = rating.direction
    if direction > 0:
        if return_pct > 1.0:
            return "aligned"
        if return_pct < -1.0:
            return "diverged"
        return "neutral"
    if direction < 0:
        if return_pct < -1.0:
            return "aligned"
        if return_pct > 1.0:
            return "diverged"
        return "neutral"
    return "neutral"


def settle_pending_decisions(
    session: Session,
    asset: Asset,
    *,
    runner: AgentRunner | None = None,
    context: AnalysisContext | None = None,
    min_age_days: int = 1,
    now: datetime | None = None,
) -> list[TradingDecisionLog]:
    """Settle unsettled decisions using strictly subsequent daily close bars."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=min_age_days)
    pending = session.scalars(
        select(TradingDecisionLog)
        .where(
            TradingDecisionLog.asset_id == asset.id,
            TradingDecisionLog.settled_at.is_(None),
            TradingDecisionLog.trade_date <= cutoff,
        )
        .order_by(TradingDecisionLog.trade_date.asc())
    ).all()
    if not pending:
        return []

    settled: list[TradingDecisionLog] = []
    for row in pending:
        # Look-ahead safe: only bars strictly after trade_date
        next_bar = session.scalar(
            select(HistoricalPrice)
            .where(
                HistoricalPrice.asset_id == asset.id,
                HistoricalPrice.timestamp > row.trade_date,
            )
            .order_by(HistoricalPrice.timestamp.desc())
            .limit(1)
        )
        if next_bar is None or row.entry_price is None or row.entry_price <= 0:
            continue

        settled_price = Decimal(str(next_bar.close))
        return_pct = float((settled_price - row.entry_price) / row.entry_price * Decimal("100"))
        row.settled_at = now or datetime.now(UTC)
        row.settled_price = settled_price
        row.realized_return_pct = round(return_pct, 4)
        row.outcome_label = _score_outcome(row.final_rating, return_pct)

        if runner is not None and context is not None:
            try:
                ref_run = runner.run(DecisionReflector(row), context)
                ref_out: DecisionReflectionOutput = ref_run.output  # type: ignore[assignment]
                row.reflection_lesson = ref_out.actionable_lesson
            except Exception:  # noqa: BLE001
                row.reflection_lesson = (
                    f"{row.final_rating.value} on {row.ticker} settled at "
                    f"{row.realized_return_pct:+.2f}% ({row.outcome_label})."
                )
        else:
            row.reflection_lesson = (
                f"{row.final_rating.value} on {row.ticker} settled at "
                f"{row.realized_return_pct:+.2f}% ({row.outcome_label})."
            )
        settled.append(row)

    session.flush()
    return settled
