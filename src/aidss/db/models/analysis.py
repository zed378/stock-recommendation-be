"""Group D - Analysis, Recommendation, Risk (Section 8.2).

Populated from Phase 4 onward. ``recommendations`` deliberately gives every
mandatory Section 5.4 field its own column rather than a free-text blob, so the
Output Validator can check completeness programmatically and the UI can render
a consistent structure.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aidss.db.base import Base, enum_column, new_uuid, utcnow
from aidss.domain.types import InvestmentHorizon, RecommendationLabel

#: Re-exported from the domain layer so `aidss.db.models` stays the one import
#: site for model consumers, while the vocabulary itself is defined once.
__all__ = [
    "AnalysisResult",
    "InvestmentHorizon",
    "PortfolioAnalysis",
    "Recommendation",
    "RecommendationLabel",
    "RiskAssessment",
]


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    analysis_type: Mapped[str] = mapped_column(String(40))
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    model_used: Mapped[str | None] = mapped_column(String(120), default=None)
    prompt_version: Mapped[str | None] = mapped_column(String(40), default=None)
    #: Snapshot of the context that produced this result - the basis of full
    #: traceability (Section 1): any output can be reproduced and audited.
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)

    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="analysis_result", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_analysis_asset_generated", "asset_id", "generated_at"),)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[RecommendationLabel] = mapped_column(enum_column(RecommendationLabel))
    confidence: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text)
    supporting_factors: Mapped[list[Any]] = mapped_column(default=list)
    #: Mandatory - an explicitly required counterweight to confirmation bias
    #: (Section 5.4).
    conflicting_factors: Mapped[list[Any]] = mapped_column(default=list)
    risk_factors: Mapped[list[Any]] = mapped_column(default=list)
    bullish_scenario: Mapped[str] = mapped_column(Text)
    bearish_scenario: Mapped[str] = mapped_column(Text)
    support_level: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    resistance_level: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    target_price_method: Mapped[str | None] = mapped_column(String(200), default=None)
    #: Named `suggested_stop`: a suggestion, never an instruction (Section 5.4).
    suggested_stop: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    horizon: Mapped[InvestmentHorizon] = mapped_column(enum_column(InvestmentHorizon, length=10))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    analysis_result: Mapped[AnalysisResult] = relationship(back_populates="recommendations")

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_confidence_range"),
    )


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    analysis_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"), default=None
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), default=None
    )
    risk_type: Mapped[str] = mapped_column(String(60))
    score: Mapped[float] = mapped_column(Float)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(analysis_result_id IS NOT NULL) OR (portfolio_id IS NOT NULL)",
            name="ck_risk_scope_present",
        ),
    )


class PortfolioAnalysis(Base):
    __tablename__ = "portfolio_analysis"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    diversification_score: Mapped[float | None] = mapped_column(Float, default=None)
    sector_concentration: Mapped[dict[str, Any]] = mapped_column(default=dict)
    correlation_matrix: Mapped[dict[str, Any]] = mapped_column(default=dict)
    narrative: Mapped[str | None] = mapped_column(Text, default=None)
    simulated_at: Mapped[datetime] = mapped_column(default=utcnow)
