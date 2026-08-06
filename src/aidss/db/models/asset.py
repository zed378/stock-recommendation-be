"""Group B - Asset & Market Data (Section 8.2)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aidss.db.base import Base, new_uuid, utcnow


class Asset(Base):
    """Master record for an instrument that can be analysed."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    exchange: Mapped[str] = mapped_column(String(20), default="IDX")
    name: Mapped[str | None] = mapped_column(String(200), default=None)
    sector: Mapped[str | None] = mapped_column(String(120), default=None)
    industry: Mapped[str | None] = mapped_column(String(120), default=None)
    currency: Mapped[str] = mapped_column(String(3), default="IDR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (UniqueConstraint("ticker", "exchange", name="uq_asset_ticker_exchange"),)


class HistoricalPrice(Base):
    """A normalised OHLCV bar.

    Unique on (asset, timeframe, timestamp), which is what makes re-fetching
    the same range idempotent - the basis of the collector's upsert.
    """

    __tablename__ = "historical_prices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column()
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    source: Mapped[str] = mapped_column(String(60))
    ingested_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "timeframe", "timestamp", name="uq_price_asset_timeframe_ts"
        ),
        Index("ix_price_asset_tf_ts", "asset_id", "timeframe", "timestamp"),
    )


class TechnicalIndicator(Base):
    """Indicator Engine output.

    ``value`` is JSON so multi-valued indicators (MACD, Bollinger, ADX) stay
    intact in one row instead of being spread across many nullable columns.
    """

    __tablename__ = "technical_indicators"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column()
    indicator_name: Mapped[str] = mapped_column(String(60))
    #: The parameters used (e.g. {"period": 14}). Part of the row identity so
    #: RSI(14) and RSI(7) never overwrite one another.
    params_key: Mapped[str] = mapped_column(String(120), default="")
    value: Mapped[dict[str, Any]] = mapped_column()
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "timeframe",
            "timestamp",
            "indicator_name",
            "params_key",
            name="uq_indicator_identity",
        ),
        Index("ix_indicator_lookup", "asset_id", "timeframe", "indicator_name", "timestamp"),
    )


class FundamentalMetric(Base):
    """Financial statement figures and ratios, per reporting period."""

    __tablename__ = "fundamental_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    period: Mapped[date] = mapped_column()
    period_type: Mapped[str] = mapped_column(String(10), default="quarterly")
    metric_name: Mapped[str] = mapped_column(String(80))
    value: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), default=None)
    source: Mapped[str] = mapped_column(String(60))
    ingested_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "period", "period_type", "metric_name", name="uq_fundamental_identity"
        ),
    )


class FeatureSnapshot(Base):
    """Feature Engineering output (Phase 3) - derived features for AI context."""

    __tablename__ = "feature_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[datetime] = mapped_column()
    features: Mapped[dict[str, Any]] = mapped_column()
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)

    asset: Mapped[Asset] = relationship()

    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "timestamp", name="uq_feature_identity"),
    )


class Issuer(Base):
    """Every company listed on IDX, whether or not the platform tracks it.

    Deliberately not the same table as ``assets``. An ``Asset`` is an
    instrument the platform holds data for and can analyse; putting all 962
    listed companies in there would advertise 962 analysable instruments while
    having prices for a handful of them. This is reference data - a directory
    used to work out who a news story is about - and it is complete precisely
    because it is not claiming to be anything more.

    Sourced from IDX's own company-profile endpoint, which is the same public
    origin the fundamentals adapter already reads.
    """

    __tablename__ = "issuers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    #: The four-letter IDX code. Unique, and the natural key everywhere else.
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    sector: Mapped[str | None] = mapped_column(String(120), default=None)
    sub_sector: Mapped[str | None] = mapped_column(String(120), default=None)
    industry: Mapped[str | None] = mapped_column(String(120), default=None)
    listing_board: Mapped[str | None] = mapped_column(String(60), default=None)
    listed_on: Mapped[date | None] = mapped_column(default=None)
    website: Mapped[str | None] = mapped_column(String(300), default=None)

    #: Names this issuer is actually called in the press, which is rarely the
    #: registered one: coverage says "Adaro", never "PT Adaro Andalan Indonesia
    #: Tbk". Derived on import and editable afterwards, because derivation
    #: cannot know that BBRI is "BRI" and that "Bank Rakyat Indonesia" is the
    #: same company.
    aliases: Mapped[list[Any]] = mapped_column(default=list)

    #: Delisted issuers are kept rather than deleted. Their news is still in the
    #: database and still refers to them, and a tag pointing at a row that no
    #: longer exists is worse than a tag pointing at a company that no longer
    #: trades.
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True)

    synced_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
