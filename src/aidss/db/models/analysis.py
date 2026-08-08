"""Group D - Analysis, Recommendation, Risk (Section 6.2).

Populated from Phase 4 onward. ``recommendations`` deliberately gives every
mandatory Section 14.4 field its own column rather than a free-text blob, so the
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

    #: The conversation this run was recorded under, which is how the result
    #: reaches the account that asked for it. Null for scheduled runs, which
    #: nobody requested and therefore nobody owns.
    #:
    #: The engine always knew both ids and stored only one, so "who asked for
    #: this analysis" was answerable at runtime and not afterwards. Sharing
    #: needs it answerable afterwards - you may only share what you own - and
    #: so does the traceability the platform claims.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"), default=None, index=True
    )

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
    #: (Section 14.4).
    conflicting_factors: Mapped[list[Any]] = mapped_column(default=list)
    risk_factors: Mapped[list[Any]] = mapped_column(default=list)
    bullish_scenario: Mapped[str] = mapped_column(Text)
    bearish_scenario: Mapped[str] = mapped_column(Text)
    support_level: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    resistance_level: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    target_price_method: Mapped[str | None] = mapped_column(String(200), default=None)
    #: Named `suggested_stop`: a suggestion, never an instruction (Section 14.4).
    suggested_stop: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), default=None)
    horizon: Mapped[InvestmentHorizon] = mapped_column(enum_column(InvestmentHorizon, length=10))

    #: Which language the prose columns above are written in.
    #:
    #: The columns hold the **original** - the text that passed schema
    #: validation and the execution-language guard. Naming its language is what
    #: makes the row below readable as renderings of it rather than as peers.
    #: No default. A default here is a guess that looks like a fact: it was
    #: "id", the writer forgot to pass the real value, and English analyses
    #: were stored claiming to be Indonesian for as long as nobody read one.
    #: Required now, so forgetting is an error at write time rather than a
    #: mislabelled row nobody can distinguish from a correct one.
    language: Mapped[str] = mapped_column(String(5))

    #: Renderings of the prose columns, keyed by language:
    #: ``{"en": {"fields": {...}, "model": "...", "translated_at": "..."}}``.
    #:
    #: One column rather than a paired `reasoning_id` / `reasoning_en` for each
    #: field, for a reason that is about meaning rather than tidiness: paired
    #: columns are symmetric, and symmetry says the two are equally
    #: authoritative. They are not. One was validated; the other is a rendering
    #: of it, and the schema should say so. A third language also costs nothing
    #: here and six more columns there.
    #:
    #: Written during the analysis run so a reader never waits for a
    #: translation they are already looking at the page for. Empty when the
    #: translation failed - which must not fail the analysis - and the
    #: on-demand `/translate` endpoint remains as the fallback.
    translations: Mapped[dict[str, Any]] = mapped_column(default=dict)

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
