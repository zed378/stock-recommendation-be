"""Group C - News, Sentiment & Scheduled Ingestion (Section 8.2).

The full pipeline (scheduled fetch -> sentiment -> embedding) is Phase 7, but
the schema is defined in Phase 1 so it never needs a second migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aidss.db.base import Base, Embedding, enum_column, new_uuid, utcnow


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    #: Repeated failures flag the schedule rather than silently disabling it
    #: (Section 6.3.3) - a schedule that stops without the user noticing is worse.
    NEEDS_ATTENTION = "needs_attention"


class NewsSource(Base):
    """An RSS or Atom feed the platform reads news from.

    Until this existed there was no real source at all: the only ``NewsProvider``
    in the tree was a fixture that manufactured plausible headlines for tests,
    and it was also the configured default - so the whole pipeline ran, reported
    success, and stored nothing anybody wrote.

    Two shapes of feed, distinguished by the URL rather than by a flag:

      * **Templated** - the URL contains ``{ticker}``. It is substituted per
        asset and the feed itself does the searching, so every entry counts.
      * **Plain** - a general headline feed. Every entry is fetched once and
        matched against the ticker and the company name, because a market-wide
        feed is mostly about other companies.

    ``asset_id`` narrows a plain feed to one issuer - an investor-relations feed,
    say - where matching would only throw away entries that all qualify.
    """

    __tablename__ = "news_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120))
    #: Unique, so the same feed cannot be added twice and then fetched twice.
    feed_url: Mapped[str] = mapped_column(String(1000), unique=True)
    #: Restricts this feed to one issuer. Null means it is read for every asset.
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), default=None, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    #: Fetch bookkeeping. Without it a feed that started returning 404 looks
    #: exactly like a feed with no news, which is the failure this whole
    #: subsystem was already in when nobody noticed for weeks.
    last_fetched_at: Mapped[datetime | None] = mapped_column(default=None)
    last_status: Mapped[str | None] = mapped_column(String(20), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    #: Entries returned by the last successful fetch, before ticker matching.
    last_entry_count: Mapped[int] = mapped_column(default=0)
    consecutive_failures: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def is_templated(self) -> bool:
        return "{ticker}" in self.feed_url


class TickerNewsSchedule(Base):
    __tablename__ = "ticker_news_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    cron_expression: Mapped[str] = mapped_column(String(120))
    preset_label: Mapped[str | None] = mapped_column(String(80), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[ScheduleStatus] = mapped_column(
        enum_column(ScheduleStatus), default=ScheduleStatus.ACTIVE
    )
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    last_fetched_at: Mapped[datetime | None] = mapped_column(default=None)
    next_run_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "asset_id", "cron_expression", name="uq_schedule_user_asset_cron"
        ),
    )


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), default=None, index=True
    )
    #: Nullable, because an article may also arrive from an on-demand fetch
    #: rather than a scheduled one.
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticker_news_schedules.id", ondelete="SET NULL"), default=None
    )
    source: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(String(1000))
    #: Hash of URL + content. Deduplicating on this still works when a URL is
    #: too long to index directly.
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    headline: Mapped[str] = mapped_column(String(500))
    body_summary: Mapped[str | None] = mapped_column(Text, default=None)
    published_at: Mapped[datetime] = mapped_column(index=True)
    #: Prevents paying for the same embedding twice on retry (Section 6.3.3).
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)

    sentiment_scores: Mapped[list[SentimentScore]] = relationship(
        back_populates="news_item", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list[NewsEmbedding]] = relationship(
        back_populates="news_item", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_news_asset_published", "asset_id", "published_at"),)


class SentimentScore(Base):
    __tablename__ = "sentiment_scores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float] = mapped_column(Float)
    model_used: Mapped[str] = mapped_column(String(120))
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    news_item: Mapped[NewsItem] = relationship(back_populates="sentiment_scores")


class NewsEmbedding(Base):
    """Kept separate from ``knowledge_chunks``: news has a time dimension and a
    per-ticker filter, so its retention strategy differs (Section 8.2)."""

    __tablename__ = "news_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    news_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(default=0)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(), default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    news_item: Mapped[NewsItem] = relationship(back_populates="embeddings")

    __table_args__ = (
        UniqueConstraint("news_item_id", "chunk_index", name="uq_news_embedding_chunk"),
    )
