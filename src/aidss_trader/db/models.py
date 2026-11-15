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

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from aidss_trader.db.base import SCHEMA, Base, Money

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


class PairRule(Base):
    """Exchange rules for one pair, refreshed before sizing (docs/03-DATA-MODEL/00)."""

    __tablename__ = "pair_rule"

    pair: Mapped[str] = mapped_column(String(16), primary_key=True)  # canonical, BTCIDR
    ticker_id: Mapped[str] = mapped_column(String(24))
    quantity_increment: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    price_increment: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    min_base_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    min_traded_qty: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Why this pair may not be traded. Empty means it passed the rules; it still
    #: has to be on the allowlist and pass the liquidity filter (ADR-005).
    blocked_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Candle(Base):
    """A closed candle. The unfinished one is never stored (docs/02-ARCHITECTURE/05)."""

    __tablename__ = "candle"
    __table_args__ = (
        UniqueConstraint("pair", "timeframe", "open_time", name="uq_candle_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pair: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(4))  # 4H | 1D
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[Decimal] = mapped_column(Money)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(24), default="indodax_ohlc")


class OrderIntentRow(Base):
    """A sized, priced proposal that passed (or failed) the Risk Engine."""

    __tablename__ = "order_intent"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    #: Deterministic identity from (strategy version, pair, signal candle, side), so
    #: re-evaluating the same candle after a restart cannot create a second intent.
    identity: Mapped[str] = mapped_column(String(160), unique=True)
    origin: Mapped[str] = mapped_column(String(10))  # LIVE | PAPER | BACKTEST
    strategy_version: Mapped[str] = mapped_column(String(64))
    pair: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))
    entry_price: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[Decimal] = mapped_column(Money)
    stop_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    risk_amount_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    rule_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskCheckResult(Base):
    """One row per check per intent, so a rejection names the limit and the numbers."""

    __tablename__ = "risk_check_result"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    intent_identity: Mapped[str] = mapped_column(String(160), index=True)
    profile: Mapped[str] = mapped_column(String(10))  # ENTRY | EMERGENCY
    check: Mapped[str] = mapped_column(String(48))
    passed: Mapped[bool] = mapped_column(Boolean)
    observed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    limit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderRow(Base):
    """An order sent to Indodax, or simulated. The row exists BEFORE the request (ADR-026)."""

    __tablename__ = "order"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    intent_identity: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(10))
    pair: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))
    type: Mapped[str] = mapped_column(String(8))  # LIMIT | MARKET
    time_in_force: Mapped[str | None] = mapped_column(String(4), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Money)
    quote_order_qty: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    #: The idempotency key. Unique: a duplicate id is how Indodax refuses a replay.
    client_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    exchange_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    full_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_qty: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    state: Mapped[str] = mapped_column(String(20), index=True)
    exchange_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: ENTRY, EXIT_TARGET, EXIT_STOP, KILL_CANCEL, KILL_FLATTEN
    purpose: Mapped[str] = mapped_column(String(16))
    reprices: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderEvent(Base):
    """Every state change of an order. Append-only."""

    __tablename__ = "order_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(f"{SCHEMA}.order.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(24))  # system | owner | killswitch | reconciler
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Fill(Base):
    """An execution. Append-only; `exchange_trade_id` makes ingestion idempotent."""

    __tablename__ = "fill"
    __table_args__ = (UniqueConstraint("origin", "exchange_trade_id", name="uq_fill_trade"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey(f"{SCHEMA}.order.id"), index=True)
    origin: Mapped[str] = mapped_column(String(10))
    exchange_trade_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pair: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[Decimal] = mapped_column(Money)
    quote_quantity: Mapped[Decimal] = mapped_column(Money)
    is_maker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: As returned by `myTrades`: fees AND taxes combined (OQ-5). The split columns stay
    #: NULL unless a source provides them; they are never estimated.
    commission: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    fee: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    tax: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    clearing: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    """Append-only. A correction is a new ADJUSTMENT row with a reason, never an edit."""

    __tablename__ = "ledger_entry"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(10))
    fill_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.fill.id"), nullable=True
    )
    entry_type: Mapped[str] = mapped_column(String(24))
    asset: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Money)  # signed
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PositionStop(Base):
    """The bot-side stop for an open position (ADR-007). Tightened, never widened."""

    __tablename__ = "position_stop"
    __table_args__ = (UniqueConstraint("pair", "origin", name="uq_position_stop"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pair: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(String(10))
    stop_price: Mapped[Decimal] = mapped_column(Money)
    target_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingStateRow(Base):
    """The global trading state. One row. There is no automatic way back to RUNNING."""

    __tablename__ = "trading_state"

    name: Mapped[str] = mapped_column(String(16), primary_key=True)  # always "trader"
    state: Mapped[str] = mapped_column(String(12))  # RUNNING | HALTED | CANCELLING | FLATTENING
    reason: Mapped[str] = mapped_column(String(200))
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[str] = mapped_column(String(64))


class KillSwitchEvent(Base):
    __tablename__ = "kill_switch_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tier: Mapped[str] = mapped_column(String(8))  # HALT | CANCEL | FLATTEN
    trigger: Mapped[str] = mapped_column(String(16))
    requested_by: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KillSwitchStep(Base):
    """One step of a kill action, so a partial FLATTEN is visible step by step."""

    __tablename__ = "kill_switch_step"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.kill_switch_event.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(12))  # ok | failed | skipped
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BreakerEvent(Base):
    __tablename__ = "breaker_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    breaker: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(8))  # HALT | CANCEL (never FLATTEN, ADR-036)
    observed: Mapped[str] = mapped_column(String(64))
    limit: Mapped[str] = mapped_column(String(64))
    tripped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    differences: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(String(12))  # clean | differences | failed


class ReconciliationDifference(Base):
    """A mismatch. Never auto-corrected: it halts trading and waits for the owner."""

    __tablename__ = "reconciliation_difference"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.reconciliation_run.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(80))
    local_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exchange_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class StrategyRow(Base):
    """A strategy's current version and mode. A new version returns it to PAPER (ADR-020)."""

    __tablename__ = "strategy"

    strategy_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(10))  # PAPER | APPROVAL | AUTO
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModeChange(Base):
    __tablename__ = "mode_change"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[str] = mapped_column(String(48), index=True)
    from_mode: Mapped[str] = mapped_column(String(10))
    to_mode: Mapped[str] = mapped_column(String(10))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    by: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ApprovalRow(Base):
    __tablename__ = "approval"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    intent_identity: Mapped[str] = mapped_column(
        String(160), unique=True
    )  # one decision per intent
    intent_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(12))  # AWAITING | APPROVED | DENIED | EXPIRED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class TradingEvent(Base):
    """An operator-facing event, stored before any delivery is attempted (FR-T32)."""

    __tablename__ = "trading_event"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(8))  # INFO | WARN | CRITICAL
    message: Mapped[str] = mapped_column(String(400))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile: Mapped[str] = mapped_column(String(12))  # none | pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StepUpGrant(Base):
    __tablename__ = "step_up_grant"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(24))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TraderSetting(Base):
    """Owner-set operational settings that are not risk limits: allowlist, liquidity filter,
    strategy parameters. Every change is audited by the code that makes it."""

    __tablename__ = "trader_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(64))


class EquitySnapshot(Base):
    """Account equity in IDR at a moment, so drawdown has a peak to be measured from."""

    __tablename__ = "equity_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    equity_idr: Mapped[Decimal] = mapped_column(Money)


class PaperEquitySnapshot(Base):
    """Simulated equity, kept apart from `equity_snapshot` so a paper figure can never become
    the peak a live drawdown is measured from (FR-T28)."""

    __tablename__ = "paper_equity_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    equity_idr: Mapped[Decimal] = mapped_column(Money)


class BacktestRunRow(Base):
    """A reproducible backtest result, labelled BACKTEST and stored as evidence for the
    PAPER -> APPROVAL promotion gate (`docs/05-MODULE-SPECIFICATIONS/06`, `11`)."""

    __tablename__ = "backtest_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(10), default="BACKTEST")
    strategy_id: Mapped[str] = mapped_column(String(48), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64), index=True)
    pair: Mapped[str] = mapped_column(String(24))
    timeframe: Mapped[str] = mapped_column(String(8), default="4H")
    candles_used: Mapped[int] = mapped_column(Integer)
    trades: Mapped[int] = mapped_column(Integer)
    wins: Mapped[int] = mapped_column(Integer)
    win_rate_pct: Mapped[Decimal] = mapped_column(Money)
    total_return_pct: Mapped[Decimal] = mapped_column(Money)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Money)
    profit_factor: Mapped[Decimal] = mapped_column(Money)
    start_equity_idr: Mapped[Decimal] = mapped_column(Money)
    final_equity_idr: Mapped[Decimal] = mapped_column(Money)
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSON)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    data_fingerprint: Mapped[str] = mapped_column(String(64))
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ran_by: Mapped[str] = mapped_column(String(64))

