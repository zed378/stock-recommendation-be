"""Operational overview for the admin dashboard (Phase 8, Section 7, 12.9).

Answers the questions an operator actually has: is data flowing, is the AI
layer working, what is it costing, and what needs attention.

Everything here is read from what the system already records - ingestion runs,
ai_messages, schedule status. Nothing is recomputed or estimated, so the
dashboard reports the same figures the audit trail does rather than a second,
subtly different set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.db.models import (
    AIMessage,
    AnalysisResult,
    Asset,
    HistoricalPrice,
    JobStatus,
    NewsItem,
    ProviderIngestionRun,
    Recommendation,
    ScheduleStatus,
    TickerNewsSchedule,
    User,
)
from aidss.plugins.registry import registry_snapshot

#: Default reporting window for the cost and activity figures.
DEFAULT_WINDOW_DAYS = 7


@dataclass(slots=True)
class OperationsOverview:
    generated_at: datetime
    window_days: int
    inventory: dict[str, Any]
    ingestion: dict[str, Any]
    ai_usage: dict[str, Any]
    attention: list[dict[str, Any]]
    providers: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "window_days": self.window_days,
            "inventory": self.inventory,
            "ingestion": self.ingestion,
            "ai_usage": self.ai_usage,
            "attention": self.attention,
            "providers": self.providers,
        }


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def build_overview(
    session: Session, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> OperationsOverview:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=window_days)

    inventory = {
        "users": _count(session, User),
        "assets": _count(session, Asset),
        "price_bars": _count(session, HistoricalPrice),
        "news_items": _count(session, NewsItem),
        "analyses": _count(session, AnalysisResult),
        "recommendations": _count(session, Recommendation),
        "active_schedules": int(
            session.scalar(
                select(func.count())
                .select_from(TickerNewsSchedule)
                .where(TickerNewsSchedule.is_active.is_(True))
            )
            or 0
        ),
    }

    runs = session.scalars(
        select(ProviderIngestionRun).where(ProviderIngestionRun.started_at >= since)
    ).all()
    failed = [r for r in runs if r.status is JobStatus.FAILED]
    ingestion = {
        "runs": len(runs),
        "failed": len(failed),
        # Reported as a fraction of what ran, with the denominator alongside:
        # "100% success" over two runs is a different claim from over two
        # thousand, and a bare percentage hides which one it is.
        "success_rate": round(1 - len(failed) / len(runs), 4) if runs else None,
        "bars_ingested": sum(r.inserted_count + r.updated_count for r in runs),
        "bars_rejected": sum(r.rejected_count for r in runs),
        "last_run_at": max((r.started_at for r in runs), default=None),
        "recent_failures": [
            {
                "provider": r.provider_name,
                "timeframe": r.timeframe,
                "error": r.error,
                "at": r.started_at.isoformat(),
            }
            for r in sorted(failed, key=lambda r: r.started_at, reverse=True)[:5]
        ],
    }
    if ingestion["last_run_at"] is not None:
        ingestion["last_run_at"] = ingestion["last_run_at"].isoformat()

    messages = session.scalars(select(AIMessage).where(AIMessage.created_at >= since)).all()
    by_agent: dict[str, dict[str, Any]] = {}
    total_cost = Decimal("0")
    for message in messages:
        agent = message.agent_name or "unattributed"
        bucket = by_agent.setdefault(agent, {"calls": 0, "tokens": 0, "cost": Decimal("0")})
        bucket["tokens"] += message.prompt_tokens + message.completion_tokens
        if message.role == "assistant":
            # Counted once per exchange rather than once per row: a prompt and
            # its answer are one call, not two.
            bucket["calls"] += 1
        if message.cost_estimate:
            bucket["cost"] += message.cost_estimate
            total_cost += message.cost_estimate

    ai_usage = {
        "total_tokens": sum(b["tokens"] for b in by_agent.values()),
        "total_calls": sum(b["calls"] for b in by_agent.values()),
        "estimated_cost": str(total_cost),
        "by_agent": {
            agent: {"calls": b["calls"], "tokens": b["tokens"], "cost": str(b["cost"])}
            for agent, b in sorted(by_agent.items())
        },
        "note": (
            "Costs are estimates from the configured price table, not billed amounts "
            "(Section 16.9)."
        ),
    }

    attention: list[dict[str, Any]] = []
    flagged = session.scalars(
        select(TickerNewsSchedule).where(
            TickerNewsSchedule.status == ScheduleStatus.NEEDS_ATTENTION
        )
    ).all()
    for schedule in flagged:
        asset = session.get(Asset, schedule.asset_id)
        attention.append(
            {
                "kind": "news_schedule",
                "detail": (
                    f"Schedule for {asset.ticker if asset else 'unknown'} has failed "
                    f"{schedule.consecutive_failures} times in a row"
                ),
                "id": str(schedule.id),
            }
        )
    for failure in ingestion["recent_failures"]:
        attention.append(
            {
                "kind": "ingestion_failure",
                "detail": f"{failure['provider']}: {failure['error']}",
                "id": None,
            }
        )

    return OperationsOverview(
        generated_at=now,
        window_days=window_days,
        inventory=inventory,
        ingestion=ingestion,
        ai_usage=ai_usage,
        attention=attention,
        providers={"registered": registry_snapshot()},
    )
