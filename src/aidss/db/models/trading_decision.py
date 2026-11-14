"""TradingAgents decision log & settlement/reflection model.

Records multi-agent debate outcomes, stance ratings, and post-settlement
reflection lessons so the Portfolio Manager can learn from historical
decisions (point-in-time safe, decision support only - never order execution).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aidss.db.base import Base, enum_column, new_uuid, utcnow
from aidss.domain.types import RecommendationLabel

__all__ = ["TradingDecisionLog"]


class TradingDecisionLog(Base):
    __tablename__ = "trading_decision_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    analysis_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="SET NULL"), default=None, index=True
    )
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(24))
    trade_date: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    final_rating: Mapped[RecommendationLabel] = mapped_column(enum_column(RecommendationLabel))
    confidence: Mapped[float] = mapped_column(Float, default=50.0)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)

    investment_plan: Mapped[str] = mapped_column(Text, default="")
    trader_proposal: Mapped[str] = mapped_column(Text, default="")
    portfolio_decision: Mapped[str] = mapped_column(Text, default="")
    debate_trace: Mapped[dict[str, Any]] = mapped_column(default=dict)

    # Settlement & reflection fields (populated strictly after trade_date)
    settled_at: Mapped[datetime | None] = mapped_column(default=None)
    settled_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    realized_return_pct: Mapped[float | None] = mapped_column(Float, default=None)
    outcome_label: Mapped[str | None] = mapped_column(String(24), default=None)
    reflection_lesson: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_trading_decision_asset_date", "asset_id", "trade_date"),
        Index("ix_trading_decision_ticker_settled", "ticker", "settled_at"),
    )
