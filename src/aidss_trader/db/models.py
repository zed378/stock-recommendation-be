"""Foundation tables (T1). Orders, fills, and the ledger arrive with T3/T4.

Privileges are part of the design (docs/03-DATA-MODEL/07): `trader_rw` may
only INSERT and SELECT on `audit_log`, and may not UPDATE or DELETE a
`risk_limit` version. The grants are applied by the migration, not left to
convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aidss_trader.db.base import Base, Money

# SQLite only autoincrements an INTEGER primary key; PostgreSQL wants BIGINT.
_SEQ = BigInteger().with_variant(Integer, "sqlite")


class Credential(Base):
    """An encrypted external credential. Plaintext is never stored (ADR-014)."""

    __tablename__ = "credential"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # indodax | telegram | analysis
    ciphertext: Mapped[str] = mapped_column(Text)
    #: The last four characters only: enough to recognise a key, never to use it.
    hint: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained (docs/09-SECURITY-PRIVACY/04)."""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(_SEQ, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: The strategy's mode at the time, so a PAPER row cannot pass for a live one.
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Lease(Base):
    """The single-instance lease (ADR-027)."""

    __tablename__ = "lease"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskLimitVersion(Base):
    """One immutable version of the risk limits. Every value is nullable: unset means disabled."""

    __tablename__ = "risk_limit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    set_by: Mapped[str] = mapped_column(String(64))

    risk_per_trade_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    max_daily_loss_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    daily_loss_day_boundary: Mapped[str | None] = mapped_column(String(16), nullable=True)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    max_consecutive_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_open_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_exposure_per_pair_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    max_total_exposure_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    max_order_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    price_deviation_pct: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    freshness_limit_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trading_window: Mapped[str | None] = mapped_column(String(64), nullable=True)
