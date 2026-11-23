"""The Trader's operator API under /trader/v1 (docs/07-API-CONTRACTS/00, 01).

Hard rules, each guarded by a test that enumerates the OpenAPI document:

* every route declares a permission and the Trader enforces it;
* there is no order-entry route and nothing about withdrawal, deposit, or fiat;
* no response schema carries a secret-like field;
* every mutating route needs an `Idempotency-Key`; destructive tiers need a
  confirmation that restates the effect; FLATTEN, promotion to AUTO, and loosening a
  limit also need a step-up grant (ADR-046);
* `/kill` uses only the kill switch, so it works with the strategy engine stopped.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, Literal, TypeVar

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from aidss_trader.api import permissions as perm
from aidss_trader.approvals import ApprovalRefused, ApprovalWorkflow, intent_hash
from aidss_trader.audit import AuditLogger
from aidss_trader.auth.stepup import StepUp, StepUpRefused
from aidss_trader.auth.verify import AuthFailed, Principal, TokenVerifier
from aidss_trader.backtest.jobs import BacktestJobs, summarise
from aidss_trader.config import RiskLimits, load_risk_limits, save_risk_limits, unset_risk_fields
from aidss_trader.config import get_settings as get_trader_settings
from aidss_trader.connector.errors import ConnectorError
from aidss_trader.connector.port import ExchangeClient
from aidss_trader.credentials import CredentialStore, CredentialUnreadable
from aidss_trader.credentials.admin import check_account
from aidss_trader.db.models import (
    ApprovalRow,
    AuditLog,
    BacktestRunRow,
    BuilderReview,
    EquitySnapshot,
    Fill,
    IdempotencyRecord,
    LedgerEntry,
    OrderIntentRow,
    OrderRow,
    PaperEquitySnapshot,
    ReconciliationDifference,
    ReconciliationRun,
    SignalAckRow,
    SignalCandidate,
    SignalScan,
    SignalTrade,
    StrategyRow,
    TradingEvent,
)
from aidss_trader.export import export_audit, export_ledger
from aidss_trader.intents import Intent, intent_from_row
from aidss_trader.killswitch import KillSwitch, KillSwitchRefused
from aidss_trader.notify import Notifier
from aidss_trader.orders.state import TERMINAL
from aidss_trader.paper import CostModel, PaperConfig
from aidss_trader.promotion import Promotion, PromotionRefused, SuppliedEvidence, Thresholds
from aidss_trader.runtime.accounting import (
    ZERO,
    daily_loss,
    drawdown_pct,
    paper_drawdown_pct,
    replay_origin,
)
from aidss_trader.runtime.builder_reviews import (
    ReviewBody,
    build_work,
    pending_work,
    review_is_current,
    review_outcome,
)
from aidss_trader.runtime.ownership import (
    REFERENCE,
    OwnershipError,
    paper_ownership,
    strategy_stats,
)
from aidss_trader.runtime.pair_selection import spread_pct as pair_spread_pct
from aidss_trader.runtime.settings_store import (
    MAX_ALL_PAIRS_LIMIT,
    MAX_ENABLED_STRATEGIES,
    MAX_HISTORY_BARS,
    THRESHOLD_FIELDS,
    Allowlist,
    LiquidityFilter,
    PaperSettings,
    StrategyDef,
    delete_strategy_def,
    duplicate_strategy_def,
    enabled_strategy_ids,
    get_allowlist,
    get_pair_groups,
    get_paper_settings,
    get_promotion_thresholds,
    get_strategy_def,
    get_strategy_params,
    list_strategy_defs,
    paper_flatters,
    set_allowlist,
    set_pair_groups,
    set_paper_settings,
    set_promotion_thresholds,
    set_strategy_def,
    set_strategy_enabled,
    set_strategy_params,
    threshold_problem,
    thresholds_loosen,
)
from aidss_trader.signals_config import (
    DEFAULT_TOP_N,
    MAX_TOP_N,
    VALID_HORIZONS,
    SignalSettingsError,
    daily_unset_fields,
    get_settings_row,
    get_signal_settings,
    parse_settings,
    request_run,
    set_signal_settings,
    unset_fields,
)
from aidss_trader.signals_config import loosens as signals_loosen
from aidss_trader.signals_stats import Row as SignalStatsRow
from aidss_trader.signals_stats import summarize as signals_summarize
from aidss_trader.strategy.declarative import BuilderDefinition
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy
from aidss_trader.strategy.kinds import ID_PATTERN, KINDS, MAX_LABEL, ParameterError, build_strategy

PREFIX = "/trader/v1"
MAX_PAIR_GROUPS = 50
MAX_GROUP_NAME = 40
MAX_GROUP_PAIRS = 500
CONFIRMATION = {
    "CANCEL": "CANCEL ALL OPEN ORDERS",
    "FLATTEN": "SELL ALL HOLDINGS AT MARKET",
}


@dataclass(slots=True)
class ApiContext:
    session_factory: Callable[[], Session]
    verifier: TokenVerifier
    stepup: Callable[[Session], StepUp]
    notifier: Callable[[Session], Notifier]
    killswitch: Callable[[Session], KillSwitch]
    submit_approved: Callable[[Session, Intent], Any]  # re-checks risk, then sends
    thresholds: Callable[[], Thresholds]
    freshness: Callable[[], tuple[datetime, bool]]  # (as_of, stale): required, never assumed fresh
    # Credential administration. Each default means "not available", so an app built without
    # them can still serve everything else and refuses credential changes instead of guessing.
    credentials: Callable[[Session], CredentialStore | None] = lambda s: None
    exchange_client_for: Callable[[str, str], ExchangeClient | None] = lambda k, s: None
    stored_exchange_client: Callable[[], ExchangeClient | None] = lambda: None
    telegram_send: Callable[[str, str, str], None] | None = None


class ApiError(Exception):
    def __init__(self, status: int, cls: str, code: str, message: str) -> None:
        self.status, self.cls, self.code, self.message = status, cls, code, message


def _meta(ctx: ApiContext, origin: str = "LIVE", source: str = "local") -> dict[str, Any]:
    as_of, stale = ctx.freshness()
    return {"source": source, "origin": origin, "as_of": as_of.isoformat(), "stale": stale}


def _cell(v: Any) -> Any:
    if isinstance(v, datetime):
        # SQLite hands back naive values; PostgreSQL aware ones. Stored values are UTC, and a
        # browser reads an offset-less timestamp as local time, so say UTC explicitly.
        return (v.replace(tzinfo=UTC) if v.tzinfo is None else v).isoformat()
    if hasattr(v, "as_tuple"):
        # Numeric columns come back padded to their scale; show 1236777000, not 1236777000.000...
        return format(v.normalize(), "f")
    return str(v) if isinstance(v, uuid.UUID) else v


def _row(obj: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in columns:
        v = getattr(obj, c)
        out[c] = _cell(v)
    return out


class KillBody(BaseModel):
    tier: str
    confirmation: str | None = None


class DecisionBody(BaseModel):
    intent_hash: str | None = None
    reason: str | None = None


class PromoteBody(BaseModel):
    note: str | None = None
    backtest_return_pct: str | None = None
    paper_drawdown_pct: str | None = None
    live_capital_used_idr: str | None = None
    slippage_vs_paper_pct: str | None = None


class DemoteBody(BaseModel):
    to_mode: str
    note: str | None = None


class ResumeBody(BaseModel):
    note: str


class StepUpBody(BaseModel):
    email: str
    password: str
    scope: str


class AllowlistBody(BaseModel):
    pairs: list[str]
    min_quote_volume_24h_idr: str | None = None
    max_spread_pct: str | None = None
    # ALL: every IDR market that passes the liquidity filter, best volume first, at most
    # `max_pairs` of them. Inactive until `max_pairs` is set.
    all_pairs: bool = False
    max_pairs: int | None = Field(default=None, ge=1, le=MAX_ALL_PAIRS_LIMIT)


class PairGroup(BaseModel):
    name: str
    pairs: list[str]


class PairGroupsBody(BaseModel):
    groups: list[PairGroup]


class PairGroupsData(BaseModel):
    groups: list[PairGroup]


class CatalogPair(BaseModel):
    pair: str
    asset: str
    min_order_idr: str | None
    trading: bool
    quote_volume_24h_idr: str | None
    spread_pct: str | None


class CatalogData(BaseModel):
    pairs: list[CatalogPair]


class ParametersBody(BaseModel):
    ema_fast: int
    ema_slow: int
    adx_period: int
    adx_threshold: str
    atr_period: int
    atr_stop_multiple: str
    cooldown_s: int


class CredentialBody(BaseModel):
    """Write-only. These fields are never returned, logged, or echoed in an error."""

    key: str
    secret: str = ""


class PaperBody(BaseModel):
    slippage_pct: str
    partial_fill_fraction: str
    maker_fee_pct: str
    taker_fee_pct: str
    tax_pct: str
    clearing_pct: str
    start_equity_idr: str


class LimitsBody(BaseModel):
    limits: dict[str, str | int | None]


class PromotionThresholdsBody(BaseModel):
    min_paper_trades: int | None = None
    max_paper_drawdown_pct: str | None = None
    backtest_min_return_pct: str | None = None
    max_live_capital_idr: str | None = None
    max_slippage_pct: str | None = None


T = TypeVar("T")
TradingStateLiteral = Literal["RUNNING", "HALTED", "CANCELLING", "FLATTENING"]
ModeLiteral = Literal["PAPER", "APPROVAL", "AUTO"]
OriginLiteral = Literal["LIVE", "PAPER", "BACKTEST"]


class MetaModel(BaseModel):
    source: str
    origin: str
    as_of: str
    stale: bool


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: MetaModel


class StatusData(BaseModel):
    trading_state: TradingStateLiteral
    unset_limits: list[str]
    modes: dict[str, ModeLiteral]


class OpenOrderModel(BaseModel):
    pair: str
    side: Literal["BUY", "SELL"]
    type: Literal["LIMIT", "MARKET"]
    state: str
    client_order_id: str


class PendingApprovalModel(BaseModel):
    intent_identity: str
    expires_at: str


class DashboardData(BaseModel):
    trading_state: TradingStateLiteral
    open_orders: list[OpenOrderModel]
    approvals_pending: list[PendingApprovalModel]


class StrategyItem(BaseModel):
    strategy_id: str
    version: str
    mode: ModeLiteral
    since: str


class GateModel(BaseModel):
    name: str
    measured: str | None
    threshold: str | None
    passed: bool
    reason: str


class PromotionData(BaseModel):
    mode: ModeLiteral
    next: ModeLiteral | None
    gates: list[GateModel]


class ApprovalCardModel(BaseModel):
    state: Literal["AWAITING", "APPROVED", "DENIED", "EXPIRED"]
    expires_at: str
    decided_by: str | None
    reason: str | None


class IntentItem(BaseModel):
    identity: str
    origin: str
    pair: str
    side: Literal["BUY", "SELL"]
    entry_price: str
    quantity: str
    stop_price: str | None
    risk_amount_idr: str | None
    state: str
    created_at: str
    intent_hash: str
    approval: ApprovalCardModel | None


class OrderItem(BaseModel):
    origin: str
    pair: str
    side: str
    type: str
    price: str | None
    quantity: str
    executed_qty: str
    state: str
    purpose: str
    submitted_at: str


class LedgerItem(BaseModel):
    at: str
    origin: str
    entry_type: str
    asset: str
    amount: str
    reason: str | None


class TradingEventItem(BaseModel):
    id: str
    kind: str
    severity: Literal["INFO", "WARN", "CRITICAL"]
    message: str
    created_at: str
    acked_at: str | None
    mobile: str


class LimitsData(BaseModel):
    limits: dict[str, str | None] | None
    unset: list[str]


class ReconciliationRunItem(BaseModel):
    started_at: str
    result: str
    differences: int


class ReconciliationDiffItem(BaseModel):
    kind: str
    reference: str
    local_value: str | None
    exchange_value: str | None


class ReconciliationData(BaseModel):
    runs: list[ReconciliationRunItem]
    unresolved: list[ReconciliationDiffItem]


class AuditItem(BaseModel):
    seq: int
    at: str
    actor: str
    action: str
    subject_type: str | None
    subject_id: str | None


class StepUpData(BaseModel):
    grant: str
    valid_for_s: int


class ApproveData(BaseModel):
    state: str
    sent: bool
    detail: str | None
    already_decided: bool


class DenyData(BaseModel):
    state: str
    already_decided: bool


class ModeData(BaseModel):
    mode: ModeLiteral


class KillData(BaseModel):
    event_id: str
    tier: Literal["HALT", "CANCEL", "FLATTEN"]


class ResumeData(BaseModel):
    trading_state: TradingStateLiteral


class PutLimitsData(BaseModel):
    version: int
    unset: list[str]


class AllowlistData(BaseModel):
    pairs: list[str]
    min_quote_volume_24h_idr: str | None
    max_spread_pct: str | None
    all_pairs: bool
    max_pairs: int | None
    active: bool


class PutAllowlistData(BaseModel):
    pairs: list[str]
    all_pairs: bool
    max_pairs: int | None
    active: bool


class StrategyParamsData(BaseModel):
    configured: bool
    params: dict[str, str] | None
    version: str | None
    mode: ModeLiteral | None
    max_history_bars: int


class PutParametersData(BaseModel):
    version: str
    mode: ModeLiteral


class StrategyDefBody(BaseModel):
    id: str
    label: str
    kind: str
    params: dict[str, str]


class StrategyDefUpdateBody(BaseModel):
    label: str
    params: dict[str, str]


class BacktestStartBody(BaseModel):
    strategy_ids: list[str] | None = None  # None: every defined strategy


class KindFieldModel(BaseModel):
    name: str
    kind: Literal["int", "decimal"]
    minimum: str
    maximum: str
    suggested: str


class KindModel(BaseModel):
    kind: str
    family: str
    fields: list[KindFieldModel]


class BacktestPairModel(BaseModel):
    pair: str
    trades: int
    wins: int
    total_return_pct: str
    max_drawdown_pct: str
    start_equity_idr: str
    ran_at: str
    ran_by: str


class StrategyDefModel(BaseModel):
    id: str
    label: str
    kind: str
    params: dict[str, str]
    legacy: bool
    version: str | None
    error: str | None
    mode: ModeLiteral | None
    backtest_pairs: int
    backtest_trades: int
    backtest_return_pct: str | None
    backtest_ran_at: str | None
    paper_enabled: bool = False
    paper_owned_pairs: list[str] = []
    backtest_expectancy_idr: str | None = None
    backtest_fees_pct: str | None = None


class PaperToggleBody(BaseModel):
    enabled: bool


class PaperTradeStats(BaseModel):
    trades: int
    wins: int
    pnl_idr: str
    drawdown_pct: str | None


class StrategyPaperData(BaseModel):
    strategy_id: str
    enabled: bool
    owned_pairs: list[str]
    claimed_pairs: list[str]
    stats: PaperTradeStats
    max_enabled: int


class BacktestSummaryModel(BaseModel):
    pairs: int
    trades: int
    wins: int
    win_rate_pct: str | None
    profit_factor: str | None
    expectancy_idr: str | None
    avg_win_idr: str | None
    avg_loss_idr: str | None
    avg_hold_hours: str | None
    fees_pct_of_start: str | None
    worst_drawdown_pct: str | None
    complete: bool


class StrategyBacktestData(BaseModel):
    strategy_id: str
    version: str | None
    pairs: list[BacktestPairModel]
    summary: BacktestSummaryModel | None = None


class BacktestJobSummaryModel(BaseModel):
    strategy_id: str
    version: str
    return_pct: str
    pairs: int
    trades: int
    skipped: list[str]


class BacktestJobData(BaseModel):
    id: str
    state: Literal["RUNNING", "DONE", "FAILED"]
    error: str | None
    current: str | None
    strategy_ids: list[str]
    done_strategies: int
    results: list[BacktestJobSummaryModel]


class SignalsConfigBody(BaseModel):
    enabled: bool = False
    mode: str = "SHADOW"
    symbols: list[str] = []
    top_n: int | None = None
    min_quote_volume_usdt: str | None = None
    horizons: list[str] = []
    min_score_ratio: str | None = None
    atr_stop_multiple: str | None = None
    tp_r: list[str] | None = None
    ai_min_score: int | None = None
    ai_max_calls: int | None = None
    h4: dict[str, Any] = {}
    notes: str = ""
    #: Required, and true, to switch to PUBLISH: a second deliberate act beside the password.
    confirm_publish: bool = False


class SignalsSettingsModel(BaseModel):
    enabled: bool
    mode: str
    symbols: list[str]
    top_n: int
    min_quote_volume_usdt: str | None
    horizons: list[str]
    min_score_ratio: str | None
    atr_stop_multiple: str | None
    tp_r: list[str | None] | None
    ai_min_score: int | None
    ai_max_calls: int | None
    h4: dict[str, Any]


class SignalsConfigData(BaseModel):
    configured: bool
    settings: SignalsSettingsModel
    unset: list[str]
    ready: bool
    default_top_n: int
    max_top_n: int
    valid_horizons: list[str]
    run_requested_at: str | None
    updated_at: str | None
    updated_by: str | None


class SignalScanModel(BaseModel):
    id: str
    kind: str
    status: str
    mode: str
    started_at: str
    finished_at: str | None
    universe: list[str]
    outcomes: dict[str, str]
    errors: list[str]
    ai_calls: int
    signals: int


class SignalsStatusData(BaseModel):
    configured: bool
    enabled: bool
    ready: bool
    mode: str
    last_scan: SignalScanModel | None
    seconds_since_last_scan: int | None
    stale: bool
    run_requested_at: str | None
    run_pending: bool


class SignalCandidateModel(BaseModel):
    id: str
    scan_id: str
    symbol: str
    day: str
    scored_at: str
    mode: str
    eligible: bool
    reason: str
    score: str
    max_score: str
    score_ratio: str
    meets_threshold: bool
    outcome: str
    met: dict[str, list[str]]
    not_met: dict[str, list[str]]
    ai: dict[str, Any] | None
    levels: dict[str, float] | None
    signal_id: str | None


class SignalCandidatesData(BaseModel):
    total: int
    items: list[SignalCandidateModel]


class SignalTradeModel(BaseModel):
    id: str
    signal_id: str
    strategy: str
    symbol: str
    side: str
    mode: str
    published: bool
    candle_open: str
    issued_at: str
    score: int
    components: dict[str, Any]
    entry: str
    stop: str
    tp1: str
    tp2: str
    tp3: str
    atr: str
    btc_bias: str
    state: str
    outcome: str | None
    tp_hits: int
    fill_price: str | None
    gross_r: str | None
    net_r: str | None
    bars_held: int
    closed_at: str | None


class SignalTradesData(BaseModel):
    total: int
    items: list[SignalTradeModel]
    simulated: bool = True


class SignalTradeSummaryData(BaseModel):
    total: int
    states: dict[str, int]
    outcomes: dict[str, int]
    overall: dict[str, Any]
    by_strategy: dict[str, dict[str, Any]]
    by_side: dict[str, dict[str, Any]]
    by_score: dict[str, dict[str, Any]]
    score_correlation: float | None
    correlation_min_closed: int
    simulated: bool
    episode_stats: dict[str, Any] = {}
    episode_stats_by_strategy: dict[str, dict[str, Any]] = {}


class SignalAckModel(BaseModel):
    id: str
    signal_id: str
    stage: str
    environment: str | None
    status: str | None
    reason: str | None
    received_at: str


class CredentialItemModel(BaseModel):
    kind: Literal["indodax", "telegram"]
    configured: bool
    hint: str | None = None
    created_at: str | None = None
    last_test_at: str | None = None
    last_test_ok: bool | None = None
    readable: bool | None = None
    reason: str | None = None


class CredentialsData(BaseModel):
    available: bool
    items: list[CredentialItemModel]


class PaperConfigData(BaseModel):
    configured: bool
    slippage_pct: str | None = None
    partial_fill_fraction: str | None = None
    maker_fee_pct: str | None = None
    taker_fee_pct: str | None = None
    tax_pct: str | None = None
    clearing_pct: str | None = None
    start_equity_idr: str | None = None
    paper_fills: int


class PutPaperData(BaseModel):
    configured: bool


class AckData(BaseModel):
    acked: bool


class PromotionThresholdsData(BaseModel):
    thresholds: dict[str, str | int | None]
    unset: list[str]


class PositionItemModel(BaseModel):
    origin: Literal["LIVE", "PAPER"]
    pair: str
    quantity: str
    avg_cost: str
    cost_basis_idr: str
    stop_price: str | None
    target_price: str | None


class OriginPortfolioModel(BaseModel):
    origin: Literal["LIVE", "PAPER"]
    configured: bool
    start_equity_idr: str | None
    latest_equity_idr: str | None
    realised_pnl_idr: str
    daily_loss_idr: str
    drawdown_pct: str | None
    trades_closed: int
    positions: list[PositionItemModel]


class BacktestRunItem(BaseModel):
    id: str
    origin: Literal["BACKTEST"]
    strategy_id: str
    strategy_version: str
    pair: str
    timeframe: str
    candles_used: int
    trades: int
    wins: int
    win_rate_pct: str
    total_return_pct: str
    max_drawdown_pct: str
    profit_factor: str
    start_equity_idr: str
    final_equity_idr: str
    data_fingerprint: str
    ran_at: str
    ran_by: str


class PortfolioData(BaseModel):
    live: OriginPortfolioModel
    paper: OriginPortfolioModel
    backtests: list[BacktestRunItem]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # The API serves JSON and CSV only: nothing it returns should ever be rendered or framed.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
REPLAY_TTL_S = 24 * 3600
REPLAY_MAX = 5000


class _Replays:
    """Remembers the successful answer to a mutation, so a retried or double-clicked request with
    the same Idempotency-Key has one effect (S7).

    Answers are written to `trading.idempotency_key` (ADR-051), so a replay survives a restart.
    The in-memory copy is only a fallback for when the table cannot be reached (for example an
    older schema); the per-key lock is always in memory because one Trader process serves the API.
    """

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._factory = session_factory
        self._items: dict[str, tuple[float, str, int, bytes, str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def get(self, key: str) -> tuple[float, str, int, bytes, str] | None:
        if self._factory is not None:
            try:
                with self._factory() as s:
                    row = s.get(IdempotencyRecord, key)
                    if row is not None:
                        created = row.created_at
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=UTC)
                        if (datetime.now(UTC) - created).total_seconds() > REPLAY_TTL_S:
                            return None
                        return (
                            0.0,
                            row.body_hash,
                            row.status_code,
                            row.response_body.encode(),
                            row.media_type,
                        )
            except Exception:  # noqa: BLE001 - fall back to the in-memory copy
                pass
        hit = self._items.get(key)
        if hit is not None and time.monotonic() - hit[0] > REPLAY_TTL_S:
            self._items.pop(key, None)
            return None
        return hit

    def put(self, key: str, body_hash: str, status: int, body: bytes, media: str) -> None:
        if len(self._items) >= REPLAY_MAX:
            oldest = min(self._items, key=lambda k: self._items[k][0])
            self._items.pop(oldest, None)
            self._locks.pop(oldest, None)
        self._items[key] = (time.monotonic(), body_hash, status, body, media)
        if self._factory is None:
            return
        now = datetime.now(UTC)
        try:
            with self._factory() as s:
                s.merge(
                    IdempotencyRecord(
                        key_hash=key,
                        body_hash=body_hash,
                        status_code=status,
                        response_body=body.decode("utf-8", errors="replace"),
                        media_type=media[:64],
                        created_at=now,
                    )
                )
                s.commit()
        except Exception:  # noqa: BLE001 - the memory copy still covers a double click
            return
        self._prune_expired(now)

    def _prune_expired(self, now: datetime) -> None:
        """Opportunistically delete rows older than REPLAY_TTL_S (ADR-051).

        Runs in its own transaction so a prune failure never fails or rolls back the API response.
        """
        cutoff = now - timedelta(seconds=REPLAY_TTL_S)
        try:
            with self._factory() as s:  # type: ignore[misc]
                s.execute(delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff))
                s.commit()
        except Exception:  # noqa: BLE001 - pruning failure is non-fatal
            pass


def _own_paper_drawdown(s: Session, strategy_id: str, since: datetime):
    """The strategy's own paper drawdown (ADR-062), or None when there is no evidence: no paper
    settings, an unattributable book, or no sale of its own since `since`."""
    ps = get_paper_settings(s)
    if ps is None:
        return None
    try:
        found = strategy_stats(paper_ownership(s), ps.start_equity_idr, since=since)
    except OwnershipError:
        return None
    stats = found.get(strategy_id)
    return None if stats is None else stats.drawdown_pct


def _backtest_summary(rows: list[BacktestRunRow]) -> dict[str, Any] | None:
    """What a strategy's latest runs say together, from raw sums (never an average of averages).

    The expectancy, average win and loss, holding time and fee figures need the sums stored since
    migration 0010; if any run predates it those figures are None rather than a partial number.
    """
    from decimal import Decimal

    if not rows:
        return None
    trades = sum(r.trades for r in rows)
    wins = sum(r.wins for r in rows)
    full = all(r.extra_metrics for r in rows)

    def total(key: str) -> Decimal:
        return sum((Decimal(str(r.extra_metrics[key])) for r in rows), Decimal(0))

    def fmt(v: Decimal | None, places: str = "0.01") -> str | None:
        return None if v is None else format(v.quantize(Decimal(places)), "f")

    win_sum = total("win_sum_idr") if full else None
    loss_sum = total("loss_sum_idr") if full else None
    losses = trades - wins
    return {
        "pairs": len(rows),
        "trades": trades,
        "wins": wins,
        "win_rate_pct": fmt(Decimal(wins) / trades * 100) if trades else None,
        "profit_factor": (
            fmt(win_sum / -loss_sum) if full and loss_sum is not None and loss_sum < 0 else None
        ),
        "expectancy_idr": fmt(total("closed_pnl_idr") / trades) if full and trades else None,
        "avg_win_idr": fmt(win_sum / wins) if full and wins and win_sum is not None else None,
        "avg_loss_idr": (
            fmt(loss_sum / losses) if full and losses and loss_sum is not None else None
        ),
        "avg_hold_hours": fmt(total("hold_hours_total") / trades, "0.1")
        if full and trades
        else None,
        "fees_pct_of_start": (
            fmt(
                sum(
                    (
                        Decimal(str(r.extra_metrics["fees_idr"])) / r.start_equity_idr * 100
                        for r in rows
                    ),
                    Decimal(0),
                ),
                "0.001",
            )
            if full
            else None
        ),
        "worst_drawdown_pct": fmt(max(r.max_drawdown_pct for r in rows), "0.001"),
        "complete": full,
    }


def create_app(ctx: ApiContext) -> FastAPI:
    app = FastAPI(title="AIDSS Trader API", docs_url=None, redoc_url=None)
    replays = _Replays(ctx.session_factory)

    @app.middleware("http")
    async def _idempotency_and_headers(request: Request, call_next):
        key = request.headers.get("idempotency-key")
        auth = request.headers.get("authorization")
        mutating = request.method in {"POST", "PUT", "DELETE", "PATCH"}
        if not (mutating and key and auth):
            response = await call_next(request)
        else:
            body = await request.body()
            body_hash = hashlib.sha256(body).hexdigest()
            # Scoped to the caller's token, the method, the path, and the key: one user's key can
            # never replay another's answer.
            ck = hashlib.sha256(
                f"{auth}|{request.method}|{request.url.path}|{key}".encode()
            ).hexdigest()
            async with replays.lock(ck):
                hit = replays.get(ck)
                if hit is not None and hit[1] != body_hash:
                    response = JSONResponse(
                        status_code=409,
                        content={
                            "error": {
                                "class": "CONFLICT",
                                "code": "idempotency_key_reused",
                                "message": "this Idempotency-Key was used for a different request",
                                "correlation_id": uuid.uuid4().hex,
                                "retryable": False,
                            }
                        },
                    )
                elif hit is not None:
                    response = Response(
                        content=hit[3],
                        status_code=hit[2],
                        media_type=hit[4],
                        headers={"Idempotent-Replay": "true"},
                    )
                else:
                    response = await call_next(request)
                    if 200 <= response.status_code < 300:
                        chunks = [c async for c in response.body_iterator]
                        payload = b"".join(chunks)
                        media = response.media_type or "application/json"
                        replays.put(ck, body_hash, response.status_code, payload, media)
                        response = Response(
                            content=payload,
                            status_code=response.status_code,
                            media_type=media,
                            headers=dict(response.headers),
                        )
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body repeats the rejected input. On a credential route that would hand
        # a key or secret straight back, so only the field names are reported, never the values.
        fields = sorted({".".join(str(p) for p in e["loc"] if p != "body") for e in exc.errors()})
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "class": "VALIDATION",
                    "code": "invalid_request",
                    "message": "invalid or missing: "
                    + (", ".join(f for f in fields if f) or "request"),
                    "correlation_id": uuid.uuid4().hex,
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "class": exc.cls,
                    "code": exc.code,
                    "message": exc.message,
                    "correlation_id": uuid.uuid4().hex,
                    "retryable": exc.status >= 500,
                }
            },
        )

    def db():
        with ctx.session_factory() as s:
            yield s

    def need(permission: str):
        def dependency(authorization: str | None = Header(default=None)) -> Principal:
            if not authorization or not authorization.lower().startswith("bearer "):
                raise ApiError(401, "AUTH", "missing_token", "authentication required")
            try:
                who = ctx.verifier.verify(authorization[7:])
            except AuthFailed:
                raise ApiError(401, "AUTH", "invalid_token", "authentication failed") from None
            if not perm.allowed(who.role, permission):
                raise ApiError(403, "FORBIDDEN", "permission_denied", f"requires {permission}")
            return who

        dependency.__permission__ = permission  # type: ignore[attr-defined]
        return dependency

    def idempotent(key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
        if not key or len(key) > 80:
            raise ApiError(
                400,
                "VALIDATION",
                "idempotency_key_required",
                "mutating routes need an Idempotency-Key header",
            )
        return key

    def step_up(s: Session, who: Principal, scope: str, grant: str | None) -> None:
        if not grant:
            raise ApiError(403, "FORBIDDEN", "step_up_required", f"{scope} needs a step-up grant")
        try:
            ctx.stepup(s).consume(grant, who, scope)
        except StepUpRefused:
            raise ApiError(
                403, "FORBIDDEN", "step_up_invalid", "step-up grant not accepted"
            ) from None

    def envelope(data: Any, origin: str = "LIVE", source: str = "local") -> dict[str, Any]:
        return {"data": data, "meta": _meta(ctx, origin, source)}

    def active_thresholds(s: Session) -> Thresholds:
        # Stored thresholds take effect when set; otherwise fall back to ctx.thresholds()
        # (so tests that inject thresholds via ApiContext continue to work seamlessly).
        stored = get_promotion_thresholds(s)
        return stored if stored != Thresholds() else ctx.thresholds()

    r = PREFIX

    # ----------------------------------------------------------------- reads

    @app.get(f"{r}/status", response_model=Envelope[StatusData])
    def status(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        state = ctx.killswitch(s).state()
        limits = load_risk_limits(s)
        modes = {x.strategy_id: x.mode for x in s.scalars(select(StrategyRow))}
        return envelope(
            {"trading_state": state, "unset_limits": unset_risk_fields(limits), "modes": modes}
        )

    @app.get(f"{r}/dashboard", response_model=Envelope[DashboardData])
    def dashboard(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        live = s.scalars(
            select(OrderRow).where(
                OrderRow.origin == "LIVE",
                OrderRow.state.in_(("OPEN", "PARTIALLY_FILLED", "CANCEL_REQUESTED", "UNKNOWN")),
            )
        ).all()
        pending = s.scalars(select(ApprovalRow).where(ApprovalRow.state == "AWAITING")).all()
        return envelope(
            {
                "trading_state": ctx.killswitch(s).state(),
                "open_orders": [
                    _row(o, ("pair", "side", "type", "state", "client_order_id")) for o in live
                ],
                "approvals_pending": [_row(a, ("intent_identity", "expires_at")) for a in pending],
            }
        )

    @app.get(f"{r}/strategies", response_model=Envelope[list[StrategyItem]])
    def strategies(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        return envelope(
            [
                _row(x, ("strategy_id", "version", "mode", "since"))
                for x in s.scalars(select(StrategyRow))
            ],
            origin="PAPER",
        )

    @app.get(f"{r}/strategies/{{strategy_id}}/promotion", response_model=Envelope[PromotionData])
    def promotion(
        strategy_id: str, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        row = s.get(StrategyRow, strategy_id)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        nxt = {"PAPER": "APPROVAL", "APPROVAL": "AUTO"}.get(row.mode)
        gates = (
            [
                asdict(g)
                for g in Promotion(s).gates(
                    strategy_id,
                    nxt,
                    active_thresholds(s),
                    SuppliedEvidence(
                        paper_drawdown_pct=_own_paper_drawdown(s, strategy_id, row.since)
                    ),
                )
            ]
            if nxt
            else []
        )
        return envelope({"mode": row.mode, "next": nxt, "gates": gates})

    @app.get(f"{r}/intents", response_model=Envelope[list[IntentItem]])
    def intents(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cols = (
            "identity",
            "origin",
            "pair",
            "side",
            "entry_price",
            "quantity",
            "stop_price",
            "risk_amount_idr",
            "state",
            "created_at",
        )
        recent = s.scalars(
            select(OrderIntentRow).order_by(OrderIntentRow.created_at.desc()).limit(200)
        ).all()
        identities = [x.identity for x in recent]
        wanted = select(ApprovalRow).where(ApprovalRow.intent_identity.in_(identities))
        approvals = {a.intent_identity: a for a in s.scalars(wanted)}
        out = []
        for row in recent:
            item = _row(row, cols)
            card = approvals.get(row.identity)
            # The hash is what an approval is bound to: the card shows this exact order and the
            # approve call must echo it back, so a card for an older price cannot approve a new one.
            item["intent_hash"] = intent_hash(_intent_from_row(row))
            item["approval"] = (
                None
                if card is None
                else {
                    "state": card.state,
                    "expires_at": _cell(card.expires_at),
                    "decided_by": card.decided_by,
                    "reason": card.reason,
                }
            )
            out.append(item)
        return envelope(out)

    @app.get(f"{r}/orders", response_model=Envelope[list[OrderItem]])
    def orders(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cols = (
            "origin",
            "pair",
            "side",
            "type",
            "price",
            "quantity",
            "executed_qty",
            "state",
            "purpose",
            "submitted_at",
        )
        return envelope(
            [
                _row(o, cols)
                for o in s.scalars(
                    select(OrderRow).order_by(OrderRow.submitted_at.desc()).limit(200)
                )
            ]
        )

    @app.get(f"{r}/ledger", response_model=Envelope[list[LedgerItem]])
    def ledger(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        return envelope(
            [
                _row(e, ("at", "origin", "entry_type", "asset", "amount", "reason"))
                for e in s.scalars(select(LedgerEntry).order_by(LedgerEntry.at.desc()).limit(500))
            ]
        )

    @app.get(f"{r}/events", response_model=Envelope[list[TradingEventItem]])
    def events(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cols = ("id", "kind", "severity", "message", "created_at", "acked_at", "mobile")
        return envelope(
            [
                _row(e, cols)
                for e in s.scalars(
                    select(TradingEvent).order_by(TradingEvent.created_at.desc()).limit(200)
                )
            ]
        )

    @app.get(f"{r}/limits", response_model=Envelope[LimitsData])
    def limits(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cur = load_risk_limits(s)
        data = None if cur is None else {k: _plain_limit(v) for k, v in asdict(cur).items()}
        return envelope({"limits": data, "unset": unset_risk_fields(cur)})  # unset shown as null

    @app.get(f"{r}/reconciliation", response_model=Envelope[ReconciliationData])
    def reconciliation(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        runs = s.scalars(
            select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc()).limit(50)
        ).all()
        diffs = s.scalars(
            select(ReconciliationDifference).where(ReconciliationDifference.resolved_at.is_(None))
        ).all()
        return envelope(
            {
                "runs": [_row(x, ("started_at", "result", "differences")) for x in runs],
                "unresolved": [
                    _row(d, ("kind", "reference", "local_value", "exchange_value")) for d in diffs
                ],
            }
        )

    @app.get(f"{r}/audit", response_model=Envelope[list[AuditItem]])
    def audit(_: Principal = Depends(need(perm.READ_AUDIT)), s: Session = Depends(db)):
        cols = ("seq", "at", "actor", "action", "subject_type", "subject_id")
        return envelope(
            [
                _row(a, cols)
                for a in s.scalars(select(AuditLog).order_by(AuditLog.seq.desc()).limit(200))
            ]
        )

    @app.get(f"{r}/export")
    def export(
        kind: str,
        start: datetime,
        end: datetime,
        who: Principal = Depends(need(perm.VIEW)),
        s: Session = Depends(db),
    ):
        if kind not in {"ledger", "audit"}:
            raise ApiError(400, "VALIDATION", "bad_kind", "kind is ledger or audit")
        if kind == "audit" and not perm.allowed(who.role, perm.READ_AUDIT):
            raise ApiError(403, "FORBIDDEN", "permission_denied", f"requires {perm.READ_AUDIT}")
        fn = export_ledger if kind == "ledger" else export_audit
        text, count = fn(s, start, end, who.user_id)
        return PlainTextResponse(text, media_type="text/csv", headers={"X-Row-Count": str(count)})

    # ---------------------------------------------------------------- writes

    @app.post(f"{r}/stepup", response_model=Envelope[StepUpData])
    def stepup(
        body: StepUpBody,
        who: Principal = Depends(need(perm.VIEW)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        try:
            token = ctx.stepup(s).issue(who, body.email, body.password, body.scope)
        except StepUpRefused as exc:
            raise ApiError(403, "FORBIDDEN", "step_up_refused", str(exc)) from None
        return envelope({"grant": token, "valid_for_s": 300})

    def _intent_from_row(row: OrderIntentRow) -> Intent:
        # Approved means it may be sent: the mode on the rebuilt intent is AUTO.
        return intent_from_row(row, mode="AUTO")

    @app.post(f"{r}/intents/{{identity}}/approve", response_model=Envelope[ApproveData])
    def approve(
        identity: str,
        body: DecisionBody,
        who: Principal = Depends(need(perm.APPROVE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        row = s.scalar(select(OrderIntentRow).where(OrderIntentRow.identity == identity))
        if row is None:
            raise ApiError(404, "NOT_FOUND", "unknown_intent", "no such intent")
        if not body.intent_hash:
            raise ApiError(
                400,
                "VALIDATION",
                "intent_hash_required",
                "approval needs the intent hash that was shown",
            )
        intent = _intent_from_row(row)
        try:
            out = ApprovalWorkflow(s, ctx.notifier(s)).approve(
                intent, who.user_id, body.intent_hash, lambda: ctx.submit_approved(s, intent)
            )
        except ApprovalRefused as exc:
            raise ApiError(409, "CONFLICT", "approval_refused", str(exc)) from None
        return envelope(
            {
                "state": out.state,
                "sent": out.sent,
                "detail": out.detail,
                "already_decided": out.already_decided,
            }
        )

    @app.post(f"{r}/intents/{{identity}}/deny", response_model=Envelope[DenyData])
    def deny(
        identity: str,
        body: DecisionBody,
        who: Principal = Depends(need(perm.APPROVE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        try:
            out = ApprovalWorkflow(s, ctx.notifier(s)).deny(identity, who.user_id, body.reason)
        except ApprovalRefused as exc:
            raise ApiError(404, "NOT_FOUND", "no_approval", str(exc)) from None
        return envelope({"state": out.state, "already_decided": out.already_decided})

    @app.post(f"{r}/strategies/{{strategy_id}}/promote", response_model=Envelope[ModeData])
    def promote(
        strategy_id: str,
        body: PromoteBody,
        who: Principal = Depends(need(perm.PROMOTE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal

        if body.backtest_return_pct is not None:
            # A figure the owner types could be edited until it passes. The gate reads the
            # stored backtest runs instead (ADR-059), so a typed one is refused, not ignored.
            raise ApiError(
                400,
                "VALIDATION",
                "typed_evidence_refused",
                "the backtest figure is read from the stored backtest runs; a typed value is "
                "not accepted",
            )
        row = s.get(StrategyRow, strategy_id)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        if strategy_id != REFERENCE:
            # Strategies built here run in the paper book only (ADR-062): there is no live
            # ownership model for them yet, so they cannot be promoted.
            raise ApiError(
                409,
                "CONFLICT",
                "paper_only",
                "only the reference strategy can be promoted; this one runs in paper only",
            )
        needs_step = row.mode == "APPROVAL"  # the next mode is AUTO
        if needs_step:
            step_up(s, who, "PROMOTE_AUTO", x_step_up)

        def d(v: str | None):
            return None if v is None else Decimal(v)

        # Paper drawdown is measured from the stored simulated equity, never typed in: a figure
        # the owner could edit before promoting would be no evidence at all.
        supplied = SuppliedEvidence(
            None,  # the backtest figure comes from stored runs (ADR-059), never from the caller
            _own_paper_drawdown(s, strategy_id, row.since),
            d(body.live_capital_used_idr),
            d(body.slippage_vs_paper_pct),
        )
        try:
            out = Promotion(s, ctx.notifier(s)).promote(
                strategy_id,
                who.user_id,
                active_thresholds(s),
                supplied,
                body.note,
                step_up_ok=needs_step,
            )
        except PromotionRefused as exc:
            raise ApiError(409, "CONFLICT", "promotion_refused", str(exc)) from None
        return envelope({"mode": out.mode})

    @app.post(f"{r}/strategies/{{strategy_id}}/demote", response_model=Envelope[ModeData])
    def demote(
        strategy_id: str,
        body: DemoteBody,
        who: Principal = Depends(need(perm.PROMOTE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        try:
            out = Promotion(s, ctx.notifier(s)).demote(
                strategy_id, who.user_id, body.to_mode, body.note
            )
        except PromotionRefused as exc:
            raise ApiError(409, "CONFLICT", "demotion_refused", str(exc)) from None
        return envelope({"mode": out.mode})

    @app.post(f"{r}/kill", response_model=Envelope[KillData])
    def kill(
        body: KillBody,
        who: Principal = Depends(need(perm.HALT)),
        _k: str = Depends(idempotent),
        x_step_up: str | None = Header(default=None),
        s: Session = Depends(db),
    ):
        if body.tier not in {"HALT", "CANCEL", "FLATTEN"}:
            raise ApiError(400, "VALIDATION", "bad_tier", "tier is HALT, CANCEL, or FLATTEN")
        # HALT is the route's floor (admin may halt, ADR-033); the heavier tiers need `kill`.
        if body.tier != "HALT" and not perm.allowed(who.role, perm.KILL):
            raise ApiError(403, "FORBIDDEN", "permission_denied", f"requires {perm.KILL}")
        if body.tier in CONFIRMATION and body.confirmation != CONFIRMATION[body.tier]:
            raise ApiError(
                400,
                "VALIDATION",
                "confirmation_required",
                f"confirmation must read: {CONFIRMATION[body.tier]}",
            )
        if body.tier == "FLATTEN":
            step_up(s, who, "FLATTEN", x_step_up)
        try:
            event = ctx.killswitch(s).activate(body.tier, "owner", who.user_id)
        except KillSwitchRefused as exc:
            raise ApiError(409, "CONFLICT", "kill_refused", str(exc)) from None
        ctx.notifier(s).emit(
            "kill_switch_used",
            f"kill switch {body.tier} used",
            {"tier": body.tier, "trigger": "owner"},
        )
        return envelope({"event_id": str(event.id), "tier": event.tier})

    @app.post(f"{r}/resume", response_model=Envelope[ResumeData])
    def resume(
        body: ResumeBody,
        who: Principal = Depends(need(perm.RESUME)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        try:
            ctx.killswitch(s).resume(body.note, who.user_id)
        except KillSwitchRefused as exc:
            raise ApiError(409, "CONFLICT", "resume_refused", str(exc)) from None
        return envelope({"trading_state": "RUNNING"})

    @app.put(f"{r}/limits", response_model=Envelope[PutLimitsData])
    def put_limits(
        body: LimitsBody,
        who: Principal = Depends(need(perm.CONFIGURE_RISK)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal, InvalidOperation

        known = set(asdict(RiskLimits()))
        unknown = set(body.limits) - known
        if unknown:
            raise ApiError(400, "VALIDATION", "unknown_limit", f"unknown: {sorted(unknown)}")
        parsed: dict[str, Any] = {}
        for k, v in body.limits.items():
            try:
                int_fields = {
                    "max_consecutive_losses",
                    "max_open_positions",
                    "freshness_limit_s",
                    "cooldown_s",
                    "order_rate_limit",
                }
                text_fields = {"daily_loss_day_boundary", "trading_window"}
                parsed[k] = (
                    v
                    if v is None or k in text_fields
                    else int(v)
                    if k in int_fields
                    else Decimal(str(v))
                )
            except (InvalidOperation, ValueError):
                raise ApiError(400, "VALIDATION", "bad_value", f"bad value for {k}") from None
            if k == "trading_window" and parsed[k] == "":
                parsed[k] = None  # an empty window means always open
            if (problem := limit_problem(k, parsed[k])) is not None:
                raise ApiError(400, "VALIDATION", "bad_value", f"{k}: {problem}")
        current = load_risk_limits(s) or RiskLimits()
        new = RiskLimits(**{**asdict(current), **parsed})
        if loosens(current, new):
            step_up(s, who, "RAISE_LIMIT", x_step_up)
        version = save_risk_limits(s, new, set_by=who.user_id)
        s.commit()
        ctx.notifier(s).emit("limit_changed", "a risk limit changed", {"version": version})
        return envelope({"version": version, "unset": unset_risk_fields(new)})

    @app.get(f"{r}/allowlist", response_model=Envelope[AllowlistData])
    def get_allow(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        a = get_allowlist(s)
        return envelope(
            {
                "pairs": list(a.pairs),
                "min_quote_volume_24h_idr": None
                if a.liquidity.min_quote_volume_24h_idr is None
                else format(a.liquidity.min_quote_volume_24h_idr.normalize(), "f"),
                "max_spread_pct": None
                if a.liquidity.max_spread_pct is None
                else format(a.liquidity.max_spread_pct.normalize(), "f"),
                "all_pairs": a.all_pairs,
                "max_pairs": a.max_pairs,
                "active": a.liquidity.configured and a.has_scope,
            }
        )

    @app.put(f"{r}/allowlist", response_model=Envelope[PutAllowlistData])
    def put_allow(
        body: AllowlistBody,
        who: Principal = Depends(need(perm.CONFIGURE_RISK)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal, InvalidOperation

        try:
            new = Allowlist(
                pairs=tuple(sorted({p.strip().upper() for p in body.pairs if p.strip()})),
                liquidity=LiquidityFilter(
                    None
                    if body.min_quote_volume_24h_idr is None
                    else Decimal(body.min_quote_volume_24h_idr),
                    None if body.max_spread_pct is None else Decimal(body.max_spread_pct),
                ),
                all_pairs=body.all_pairs,
                max_pairs=body.max_pairs,
            )
        except InvalidOperation:
            raise ApiError(
                400, "VALIDATION", "bad_value", "a liquidity number is not a decimal"
            ) from None
        # Any IDR pair may be listed, not only the first two (ADR-044). The quote currency is
        # fixed: equity is valued and orders are sized in IDR (ADR-002).
        import re

        bad = [p for p in new.pairs if not re.fullmatch(r"[A-Z0-9]{2,12}IDR", p)]
        if bad:
            raise ApiError(
                400, "VALIDATION", "bad_pair", f"only IDR pairs such as BTCIDR are supported: {bad}"
            )
        old = get_allowlist(s)
        if allowlist_loosens(old, new):
            step_up(s, who, "RAISE_LIMIT", x_step_up)
        set_allowlist(s, new, by=who.user_id)
        s.commit()
        ctx.notifier(s).emit(
            "limit_changed", "the allowlist or liquidity filter changed", {"pairs": len(new.pairs)}
        )
        return envelope(
            {
                "pairs": list(new.pairs),
                "all_pairs": new.all_pairs,
                "max_pairs": new.max_pairs,
                "active": new.liquidity.configured and new.has_scope,
            }
        )

    # --------------------------------------------- the pair catalogue and the owner's groups

    catalog_cache: dict[str, Any] = {"at": 0.0, "rows": None}

    @app.get(f"{r}/pairs-catalog", response_model=Envelope[CatalogData])
    def pairs_catalog(_: Principal = Depends(need(perm.VIEW))):
        """Every IDR market the exchange lists, with its 24 hour volume and spread, for picking
        pairs and building groups. Two public calls, cached for a minute."""
        from decimal import Decimal

        client = ctx.stored_exchange_client()
        if client is None:
            raise ApiError(
                503,
                "UNAVAILABLE",
                "no_exchange",
                "no exchange is configured, so the pair list cannot be fetched",
            )
        if catalog_cache["rows"] is None or time.monotonic() - catalog_cache["at"] > 60:
            try:
                infos = client.get_pairs()
                summaries = client.get_market_summaries()
            except ConnectorError as exc:
                raise ApiError(
                    502,
                    "UNAVAILABLE",
                    "exchange_error",
                    f"the exchange refused ({exc.error_class})",
                ) from None
            rows = []
            for info in infos:
                if not info.pair.endswith("IDR"):
                    continue
                summary = summaries.get(info.pair)
                spread = None if summary is None else pair_spread_pct(summary)
                rows.append(
                    {
                        "pair": info.pair,
                        "asset": info.quote_asset,
                        "min_order_idr": None
                        if info.min_base_idr is None
                        else format(info.min_base_idr.normalize(), "f"),
                        "trading": not (info.maintenance or info.suspended),
                        "quote_volume_24h_idr": None
                        if summary is None or summary.quote_volume_24h is None
                        else format(summary.quote_volume_24h.normalize(), "f"),
                        "spread_pct": None
                        if spread is None
                        else format(spread.quantize(Decimal("0.0001")), "f"),
                    }
                )
            rows.sort(key=lambda x: (-Decimal(x["quote_volume_24h_idr"] or "0"), x["pair"]))
            catalog_cache["rows"], catalog_cache["at"] = rows, time.monotonic()
        return envelope({"pairs": catalog_cache["rows"]}, source="exchange")

    @app.get(f"{r}/pair-groups", response_model=Envelope[PairGroupsData])
    def get_groups(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        groups = get_pair_groups(s)
        return envelope(
            {"groups": [{"name": n, "pairs": list(p)} for n, p in sorted(groups.items())]}
        )

    @app.put(f"{r}/pair-groups", response_model=Envelope[PairGroupsData])
    def put_groups(
        body: PairGroupsBody,
        who: Principal = Depends(need(perm.CONFIGURE_RISK)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        """Replace the owner's groups. A group only names pairs: selecting it copies them into the
        allowlist when that is saved (and that save is what needs the step-up), so editing a
        group changes nothing that trades."""
        import re

        if len(body.groups) > MAX_PAIR_GROUPS:
            raise ApiError(
                400, "VALIDATION", "too_many_groups", f"at most {MAX_PAIR_GROUPS} groups"
            )
        cleaned: dict[str, tuple[str, ...]] = {}
        seen: set[str] = set()
        for group in body.groups:
            name = " ".join(group.name.split())
            if not 1 <= len(name) <= MAX_GROUP_NAME:
                raise ApiError(
                    400,
                    "VALIDATION",
                    "bad_group_name",
                    f"a group name is 1 to {MAX_GROUP_NAME} characters",
                )
            if name.lower() in seen:
                raise ApiError(400, "VALIDATION", "duplicate_group", "group names must be unique")
            seen.add(name.lower())
            pairs = tuple(sorted({p.strip().upper() for p in group.pairs if p.strip()}))
            bad = [p for p in pairs if not re.fullmatch(r"[A-Z0-9]{2,12}IDR", p)]
            if bad or not pairs or len(pairs) > MAX_GROUP_PAIRS:
                raise ApiError(
                    400,
                    "VALIDATION",
                    "bad_group_pairs",
                    f"a group holds 1 to {MAX_GROUP_PAIRS} IDR pairs such as BTCIDR: {bad[:5]}",
                )
            cleaned[name] = pairs
        set_pair_groups(s, cleaned, by=who.user_id)
        s.commit()
        return envelope(
            {"groups": [{"name": n, "pairs": list(p)} for n, p in sorted(cleaned.items())]}
        )

    @app.get(
        f"{r}/strategies/{{strategy_id}}/parameters",
        response_model=Envelope[StrategyParamsData],
    )
    def get_params(
        strategy_id: str, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        if strategy_id != "ema_adx":
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        row = s.get(StrategyRow, strategy_id)
        params = get_strategy_params(s, strategy_id)
        return envelope(
            {
                "configured": params is not None,
                "params": params,
                "version": None if row is None else row.version,
                "mode": None if row is None else row.mode,
                "max_history_bars": MAX_HISTORY_BARS,
            },
            origin="PAPER",
        )

    @app.put(
        f"{r}/strategies/{{strategy_id}}/parameters",
        response_model=Envelope[PutParametersData],
    )
    def put_params(
        strategy_id: str,
        body: ParametersBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        from decimal import Decimal, InvalidOperation

        if strategy_id != "ema_adx":
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        try:
            params = EmaAdxParams(
                ema_fast=body.ema_fast,
                ema_slow=body.ema_slow,
                adx_period=body.adx_period,
                adx_threshold=Decimal(body.adx_threshold),
                atr_period=body.atr_period,
                atr_stop_multiple=Decimal(body.atr_stop_multiple),
                cooldown_s=body.cooldown_s,
            )
        except (InvalidOperation, ValueError) as exc:
            raise ApiError(400, "VALIDATION", "bad_parameters", str(exc)) from None
        needed = EmaAdxStrategy(params).min_history()
        if needed > MAX_HISTORY_BARS:
            raise ApiError(
                400,
                "VALIDATION",
                "bad_parameters",
                f"these periods need {needed} candles of history but only "
                f"{MAX_HISTORY_BARS} are kept, so the strategy could never evaluate",
            )
        version = set_strategy_params(s, strategy_id, params, by=who.user_id)
        s.commit()
        # A new version always starts again in PAPER (ADR-020); the response says so.
        return envelope({"version": version, "mode": "PAPER"})

    # ------------------------------------------------------ strategy library and backtests

    jobs = BacktestJobs(ctx.session_factory)  # type: ignore[arg-type]

    @app.get(f"{r}/signal-builder/schema", response_model=Envelope[dict[str, Any]])
    def builder_schema(_: Principal = Depends(need(perm.VIEW))):
        return envelope(BuilderDefinition.model_json_schema(), origin="PAPER")

    def need_builder_worker():
        def dependency(token: str | None = Header(default=None, alias="X-Builder-Worker-Token")):
            try:
                token_file = get_trader_settings().builder_worker_token_file
            except Exception:  # noqa: BLE001 - missing infra config means auth is unavailable
                token_file = None
            expected = ""
            if token_file is not None:
                try:
                    if os.name != "nt" and token_file.stat().st_mode & 0o077:
                        raise OSError("worker token permissions are too broad")
                    expected = token_file.read_text(encoding="utf-8").strip()
                    if len(expected) < 32:
                        expected = ""
                except OSError:
                    expected = ""
            if not expected or token is None or not hmac.compare_digest(token, expected):
                raise ApiError(
                    401, "AUTH", "invalid_worker_token", "builder worker authentication required"
                )
            return Principal(user_id="signal-worker", role="signal_worker")

        dependency.__permission__ = perm.RECORD_BUILDER_REVIEW  # type: ignore[attr-defined]
        return dependency

    @app.get(f"{r}/signal-builder/work", response_model=Envelope[list[dict[str, Any]]])
    def builder_work(_: Principal = Depends(need_builder_worker()), s: Session = Depends(db)):
        return envelope(pending_work(s, datetime.now(UTC)), origin="PAPER")

    @app.get(f"{r}/signal-builder/reviews", response_model=Envelope[list[dict[str, Any]]])
    def builder_reviews(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        rows = s.scalars(
            select(BuilderReview).order_by(BuilderReview.generated_at.desc()).limit(50)
        )
        return envelope(
            [
                {
                    "id": str(row.id),
                    "strategy_id": row.strategy_id,
                    "strategy_version": row.strategy_version,
                    "pair": row.pair,
                    "timeframe": row.timeframe,
                    "candle_open": _cell(row.candle_open),
                    "generated_at": _cell(row.generated_at),
                    "outcome": row.outcome,
                    "reason": row.reason,
                    "evidence": row.evidence,
                    "origin": "SHADOW",
                    "current": review_is_current(s, row, datetime.now(UTC)),
                }
                for row in rows
            ],
            origin="PAPER",
        )

    @app.post(f"{r}/signal-builder/reviews", response_model=Envelope[dict[str, Any]])
    def record_builder_review(
        body: ReviewBody,
        who: Principal = Depends(need_builder_worker()),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        existing = s.scalar(select(BuilderReview).where(BuilderReview.identity == body.identity))
        if existing is not None:
            if existing.evidence != body.model_dump(mode="json"):
                raise ApiError(409, "CONFLICT", "review_immutable", "a review cannot be replaced")
            return envelope({"id": str(existing.id), "outcome": existing.outcome}, origin="PAPER")
        now = datetime.now(UTC)
        work = build_work(s, body.strategy_id, body.pair, now)
        if work is None or work["identity"] != body.identity:
            raise ApiError(
                409, "CONFLICT", "review_work_changed", "review input is no longer current"
            )
        outcome, reason = review_outcome(work, body)
        row = BuilderReview(
            identity=body.identity,
            strategy_id=body.strategy_id,
            strategy_version=work["strategy_version"],
            pair=body.pair,
            timeframe=work["timeframe"],
            candle_open=datetime.fromisoformat(work["candle_open"]),
            data_hash=work["data_hash"],
            generated_at=now,
            outcome=outcome,
            reason=reason,
            evidence=body.model_dump(mode="json"),
        )
        s.add(row)
        s.flush()
        AuditLogger(s).record(
            actor=who.user_id,
            action="builder_review_recorded",
            subject_type="builder_review",
            subject_id=str(row.id),
            mode="PAPER",
            after={"identity": body.identity, "outcome": outcome, "reason": reason},
            at=now,
        )
        s.commit()
        return envelope({"id": str(row.id), "outcome": outcome}, origin="PAPER")

    def _def_version(d: StrategyDef) -> tuple[str | None, str | None]:
        try:
            return build_strategy(d.kind, d.params).version_id(), None
        except ParameterError as exc:
            return None, str(exc)

    def _latest_rows(s: Session, strategy_id: str, version: str) -> list[BacktestRunRow]:
        rows = s.scalars(
            select(BacktestRunRow)
            .where(
                BacktestRunRow.strategy_id == strategy_id,
                BacktestRunRow.strategy_version == version,
            )
            .order_by(BacktestRunRow.ran_at.desc())
        ).all()
        seen: dict[str, BacktestRunRow] = {}
        for row in rows:
            seen.setdefault(row.pair, row)
        return sorted(seen.values(), key=lambda x: x.pair)

    def _validated(kind: str, params: dict[str, str]) -> str:
        """Build the strategy the owner described, or say precisely why it cannot exist."""
        try:
            strategy = build_strategy(kind, params)
        except ParameterError as exc:
            raise ApiError(400, "VALIDATION", "bad_parameters", str(exc)) from None
        needed = strategy.min_history()
        if needed > MAX_HISTORY_BARS:
            raise ApiError(
                400,
                "VALIDATION",
                "bad_parameters",
                f"these periods need {needed} candles of history but only "
                f"{MAX_HISTORY_BARS} are kept, so the strategy could never evaluate",
            )
        return strategy.version_id()

    def _label(label: str) -> str:
        text = " ".join(label.split())
        if not text or len(text) > MAX_LABEL:
            raise ApiError(400, "VALIDATION", "bad_label", f"a name is 1 to {MAX_LABEL} characters")
        return text

    @app.get(f"{r}/strategy-kinds", response_model=Envelope[list[KindModel]])
    def strategy_kinds(_: Principal = Depends(need(perm.VIEW))):
        return envelope(
            [
                {
                    "kind": k.kind,
                    "family": k.family,
                    "fields": [
                        {
                            "name": f.name,
                            "kind": f.kind,
                            "minimum": f.minimum,
                            "maximum": f.maximum,
                            "suggested": f.suggested,
                        }
                        for f in k.fields
                    ],
                }
                for k in KINDS.values()
            ],
            origin="BACKTEST",
        )

    @app.get(f"{r}/strategy-defs", response_model=Envelope[list[StrategyDefModel]])
    def strategy_defs(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        out = []
        enabled = set(enabled_strategy_ids(s))
        try:
            book = paper_ownership(s)
            owned: dict[str, list[str]] = {}
            for pair, sid in book.owners.items():
                owned.setdefault(sid, []).append(pair)
        except OwnershipError:
            owned = {}
        for d in list_strategy_defs(s):
            version, error = _def_version(d)
            rows = [] if version is None else _latest_rows(s, d.id, version)
            summary = _backtest_summary(rows)
            row = s.get(StrategyRow, d.id) if d.legacy else None
            out.append(
                {
                    "id": d.id,
                    "label": d.label,
                    "kind": d.kind,
                    "params": d.params,
                    "legacy": d.legacy,
                    "version": version,
                    "error": error,
                    "mode": None if row is None else row.mode,
                    "backtest_pairs": len(rows),
                    "backtest_trades": sum(x.trades for x in rows),
                    "backtest_return_pct": (
                        _cell(sum((x.total_return_pct for x in rows), ZERO)) if rows else None
                    ),
                    "backtest_ran_at": _cell(max(x.ran_at for x in rows)) if rows else None,
                    "paper_enabled": d.id in enabled,
                    "paper_owned_pairs": sorted(owned.get(d.id, [])),
                    "backtest_expectancy_idr": (summary or {}).get("expectancy_idr"),
                    "backtest_fees_pct": (summary or {}).get("fees_pct_of_start"),
                }
            )
        return envelope(out, origin="PAPER")

    @app.post(f"{r}/strategy-defs", response_model=Envelope[StrategyDefModel], status_code=201)
    def create_strategy_def(
        body: StrategyDefBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        import re

        if not re.fullmatch(ID_PATTERN, body.id):
            raise ApiError(
                400,
                "VALIDATION",
                "bad_id",
                "an id is 2 to 32 characters: lowercase letters, digits and underscores, "
                "starting with a letter",
            )
        if body.id == "ema_adx":
            raise ApiError(
                409, "CONFLICT", "reserved_id", "ema_adx is the reference strategy; edit it instead"
            )
        if get_strategy_def(s, body.id) is not None:
            raise ApiError(409, "CONFLICT", "strategy_exists", "a strategy with this id exists")
        label = _label(body.label)
        version = _validated(body.kind, body.params)
        twin = duplicate_strategy_def(s, body.kind, body.params)
        if twin is not None:
            raise ApiError(
                409,
                "CONFLICT",
                "duplicate_parameters",
                f"{twin} already has this kind and these numbers; change a number or edit it",
            )
        set_strategy_def(
            s, StrategyDef(body.id, body.kind, label, dict(body.params)), by=who.user_id
        )
        s.commit()
        d = get_strategy_def(s, body.id)
        assert d is not None
        return envelope(
            {
                "id": d.id,
                "label": d.label,
                "kind": d.kind,
                "params": d.params,
                "legacy": False,
                "version": version,
                "error": None,
                "mode": None,
                "backtest_pairs": 0,
                "backtest_trades": 0,
                "backtest_return_pct": None,
                "backtest_ran_at": None,
            },
            origin="PAPER",
        )

    @app.put(f"{r}/strategy-defs/{{strategy_id}}", response_model=Envelope[StrategyDefModel])
    def update_strategy_def(
        strategy_id: str,
        body: StrategyDefUpdateBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        existing = get_strategy_def(s, strategy_id)
        if existing is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        if existing.legacy:
            # The reference strategy's parameters are tied to its mode and promotion state, so
            # they keep their own route, which also returns it to PAPER.
            raise ApiError(
                409,
                "CONFLICT",
                "use_parameters_route",
                f"edit this strategy through PUT {PREFIX}/strategies/{strategy_id}/parameters",
            )
        label = _label(body.label)
        version = _validated(existing.kind, body.params)
        twin = duplicate_strategy_def(s, existing.kind, body.params, exclude=strategy_id)
        if twin is not None:
            raise ApiError(
                409,
                "CONFLICT",
                "duplicate_parameters",
                f"{twin} already has this kind and these numbers; change a number",
            )
        set_strategy_def(
            s, StrategyDef(strategy_id, existing.kind, label, dict(body.params)), by=who.user_id
        )
        s.commit()
        if strategy_id in enabled_strategy_ids(s) or s.get(StrategyRow, strategy_id) is not None:
            # A new version starts in PAPER (ADR-020); registering it keeps an enabled strategy
            # running. An open position it owns stays its own and is managed by the new version.
            Promotion(s).register(strategy_id, version)
        rows = _latest_rows(s, strategy_id, version)
        return envelope(
            {
                "id": strategy_id,
                "label": label,
                "kind": existing.kind,
                "params": dict(body.params),
                "legacy": False,
                "version": version,
                "error": None,
                "mode": None,
                "backtest_pairs": len(rows),
                "backtest_trades": sum(x.trades for x in rows),
                "backtest_return_pct": (
                    _cell(sum((x.total_return_pct for x in rows), ZERO)) if rows else None
                ),
                "backtest_ran_at": _cell(max(x.ran_at for x in rows)) if rows else None,
            },
            origin="PAPER",
        )

    @app.delete(f"{r}/strategy-defs/{{strategy_id}}", response_model=Envelope[dict[str, bool]])
    def delete_strategy(
        strategy_id: str,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        existing = get_strategy_def(s, strategy_id)
        if existing is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        try:
            book = paper_ownership(s)
        except OwnershipError:
            raise ApiError(
                409, "CONFLICT", "strategy_in_use", "the paper book cannot be attributed; try later"
            ) from None
        if strategy_id in book.owners.values() or strategy_id in book.claims.values():
            raise ApiError(
                409,
                "CONFLICT",
                "strategy_in_use",
                "this strategy holds a paper position or has an entry waiting to fill; "
                "disable it and let the position close first",
            )
        if existing.legacy:
            # The runtime trades this one. Removing its parameters while a position or an order
            # is open would leave something open that nothing manages.
            holding = [
                origin
                for origin in ("PAPER", "LIVE")
                if any(p.quantity > 0 for p in replay_origin(s, origin)[0].values())
            ]
            pending = s.scalar(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.state.notin_([st.value for st in TERMINAL]))
            )
            if holding or pending:
                raise ApiError(
                    409,
                    "CONFLICT",
                    "strategy_in_use",
                    "this strategy has an open position or an unfinished order; close it first",
                )
        delete_strategy_def(s, strategy_id, by=who.user_id)
        s.commit()
        return envelope({"deleted": True}, origin="PAPER")

    def _paper_data(s: Session, strategy_id: str) -> dict[str, Any]:
        ps = get_paper_settings(s)
        try:
            book = paper_ownership(s)
        except OwnershipError:
            raise ApiError(
                409, "CONFLICT", "paper_book_unattributable", "the paper book cannot be attributed"
            ) from None
        st = strategy_stats(book, ps.start_equity_idr).get(strategy_id) if ps is not None else None
        return {
            "strategy_id": strategy_id,
            "enabled": strategy_id in enabled_strategy_ids(s) or strategy_id == REFERENCE,
            "owned_pairs": sorted(p for p, o in book.owners.items() if o == strategy_id),
            "claimed_pairs": sorted(p for p, o in book.claims.items() if o == strategy_id),
            "stats": {
                "trades": 0 if st is None else st.trades,
                "wins": 0 if st is None else st.wins,
                "pnl_idr": "0" if st is None else _cell(st.pnl),
                "drawdown_pct": None
                if st is None or st.drawdown_pct is None
                else _cell(st.drawdown_pct),
            },
            "max_enabled": MAX_ENABLED_STRATEGIES,
        }

    @app.get(f"{r}/strategy-defs/{{strategy_id}}/paper", response_model=Envelope[StrategyPaperData])
    def strategy_paper(
        strategy_id: str, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        if get_strategy_def(s, strategy_id) is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        return envelope(_paper_data(s, strategy_id), origin="PAPER")

    @app.put(f"{r}/strategy-defs/{{strategy_id}}/paper", response_model=Envelope[StrategyPaperData])
    def set_strategy_paper(
        strategy_id: str,
        body: PaperToggleBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        d = get_strategy_def(s, strategy_id)
        if d is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        if strategy_id == REFERENCE:
            raise ApiError(
                409,
                "CONFLICT",
                "reference_has_own_mode",
                "the reference strategy runs according to its own mode, not this switch",
            )
        if body.enabled:
            version = _validated(d.kind, d.params)
            others = [i for i in enabled_strategy_ids(s) if i != strategy_id]
            if len(others) >= MAX_ENABLED_STRATEGIES:
                raise ApiError(
                    409,
                    "CONFLICT",
                    "too_many_enabled",
                    f"at most {MAX_ENABLED_STRATEGIES} strategies can run in paper at once",
                )
            Promotion(s).register(strategy_id, version)
        set_strategy_enabled(s, strategy_id, body.enabled, by=who.user_id)
        s.commit()
        return envelope(_paper_data(s, strategy_id), origin="PAPER")

    @app.get(
        f"{r}/strategy-defs/{{strategy_id}}/backtests",
        response_model=Envelope[StrategyBacktestData],
    )
    def strategy_backtests(
        strategy_id: str, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        d = get_strategy_def(s, strategy_id)
        if d is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        version, _err = _def_version(d)
        rows = [] if version is None else _latest_rows(s, strategy_id, version)
        return envelope(
            {
                "strategy_id": strategy_id,
                "version": version,
                "pairs": [
                    _row(
                        x,
                        (
                            "pair",
                            "trades",
                            "wins",
                            "total_return_pct",
                            "max_drawdown_pct",
                            "start_equity_idr",
                            "ran_at",
                            "ran_by",
                        ),
                    )
                    for x in rows
                ],
                "summary": _backtest_summary(rows),
            },
            origin="BACKTEST",
        )

    def _job_data(job: Any) -> dict[str, Any]:
        return {
            "id": job.id,
            "state": job.state,
            "error": job.error,
            "current": job.current,
            "strategy_ids": job.strategy_ids,
            "done_strategies": job.done_strategies,
            "results": [summarise(x) for x in job.results],
        }

    @app.post(f"{r}/backtests", response_model=Envelope[BacktestJobData], status_code=202)
    def start_backtests(
        body: BacktestStartBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        if jobs.active() is not None:
            raise ApiError(
                409, "CONFLICT", "backtest_running", "a backtest is already running; wait for it"
            )
        defs = {d.id: d for d in list_strategy_defs(s)}
        wanted = body.strategy_ids if body.strategy_ids is not None else sorted(defs)
        if not wanted:
            raise ApiError(400, "VALIDATION", "nothing_to_run", "there is no strategy to run")
        if len(set(wanted)) != len(wanted) or any(w not in defs for w in wanted):
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        for sid in wanted:
            _validated(defs[sid].kind, defs[sid].params)
        picked = [(sid, (lambda d=defs[sid]: build_strategy(d.kind, d.params))) for sid in wanted]
        job = jobs.start(picked, by=f"user:{who.user_id}")
        return envelope(_job_data(job), origin="BACKTEST")

    @app.get(f"{r}/backtests/{{job_id}}", response_model=Envelope[BacktestJobData])
    def backtest_job(job_id: str, _: Principal = Depends(need(perm.VIEW))):
        job = jobs.get(job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "unknown_job", "no such backtest job")
        return envelope(_job_data(job), origin="BACKTEST")

    # ------------------------------------------------------------ crypto signals (ADR-066)

    def _signal_config_data(s: Session) -> dict[str, Any]:
        row = get_settings_row(s)
        settings = get_signal_settings(s)
        missing = unset_fields(settings)
        raw = settings.as_json()
        return {
            "configured": row is not None,
            "settings": raw,
            "unset": missing,
            "ready": row is not None and not daily_unset_fields(settings),
            "default_top_n": DEFAULT_TOP_N,
            "max_top_n": MAX_TOP_N,
            "valid_horizons": list(VALID_HORIZONS),
            "run_requested_at": None if row is None else _cell(row.run_requested_at),
            "updated_at": None if row is None else _cell(row.updated_at),
            "updated_by": None if row is None else row.updated_by,
        }

    def _scan_row(x: SignalScan) -> dict[str, Any]:
        return {
            "id": str(x.id),
            "kind": x.kind,
            "status": x.status,
            "mode": x.mode,
            "started_at": _cell(x.started_at),
            "finished_at": _cell(x.finished_at),
            "universe": list(x.universe or []),
            "outcomes": dict(x.outcomes or {}),
            "errors": [str(e) for e in (x.errors or [])],
            "ai_calls": x.ai_calls,
            "signals": x.signals,
        }

    @app.get(f"{r}/signals/config", response_model=Envelope[SignalsConfigData])
    def get_signals_config(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        return envelope(_signal_config_data(s), origin="PAPER")

    @app.put(f"{r}/signals/config", response_model=Envelope[SignalsConfigData])
    def put_signals_config(
        body: SignalsConfigBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        try:
            new = parse_settings(body.model_dump())
        except SignalSettingsError as exc:
            raise ApiError(400, "VALIDATION", "bad_settings", "; ".join(exc.problems)) from None
        old = get_signal_settings(s)
        if new.mode == "PUBLISH" and not body.confirm_publish:
            raise ApiError(
                400,
                "VALIDATION",
                "confirm_publish_required",
                "switching to PUBLISH needs the explicit confirmation",
            )
        if new.mode == "PUBLISH" and (new.enabled and unset_fields(new)):
            raise ApiError(
                400,
                "VALIDATION",
                "bad_settings",
                "cannot publish while these are unset: " + ", ".join(unset_fields(new)),
            )
        if signals_loosen(old, new):
            step_up(s, who, "RAISE_LIMIT", x_step_up)
        set_signal_settings(s, new, by=who.user_id)
        s.commit()
        return envelope(_signal_config_data(s), origin="PAPER")

    @app.post(f"{r}/signals/run", response_model=Envelope[SignalsConfigData], status_code=202)
    def run_signals_now(
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        settings = get_signal_settings(s)
        if get_settings_row(s) is None or not settings.enabled or daily_unset_fields(settings):
            raise ApiError(
                409,
                "CONFLICT",
                "not_ready",
                "the worker is not enabled or has unset settings; nothing to scan",
            )
        request_run(s, by=who.user_id)
        s.commit()
        return envelope(_signal_config_data(s), origin="PAPER")

    @app.get(f"{r}/signals/status", response_model=Envelope[SignalsStatusData])
    def get_signals_status(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        row = get_settings_row(s)
        settings = get_signal_settings(s)
        last = s.scalars(select(SignalScan).order_by(SignalScan.started_at.desc()).limit(1)).first()
        ready = row is not None and not daily_unset_fields(settings)
        age = None
        if last is not None:
            started = last.started_at
            started = started.replace(tzinfo=UTC) if started.tzinfo is None else started
            age = max(0, int((datetime.now(UTC) - started).total_seconds()))
        stale = bool(settings.enabled and ready and (age is None or age > 36 * 3600))
        requested = None if row is None else row.run_requested_at
        pending = False
        if requested is not None:
            req = requested.replace(tzinfo=UTC) if requested.tzinfo is None else requested
            started = None
            if last is not None:
                started = (
                    last.started_at.replace(tzinfo=UTC)
                    if last.started_at.tzinfo is None
                    else last.started_at
                )
            pending = started is None or started < req
        return envelope(
            {
                "configured": row is not None,
                "enabled": settings.enabled,
                "ready": ready,
                "mode": settings.mode,
                "last_scan": None if last is None else _scan_row(last),
                "seconds_since_last_scan": age,
                "stale": stale,
                "run_requested_at": None if requested is None else _cell(requested),
                "run_pending": pending,
            },
            origin="PAPER",
        )

    def _trade_row(x: SignalTrade) -> dict[str, Any]:
        return {
            "id": str(x.id),
            "signal_id": x.signal_id,
            "strategy": x.strategy,
            "symbol": x.symbol,
            "side": x.side,
            "mode": x.mode,
            "published": x.published,
            "candle_open": _cell(x.candle_open),
            "issued_at": _cell(x.issued_at),
            "score": x.score,
            "components": dict(x.components or {}),
            "entry": _cell(x.entry),
            "stop": _cell(x.stop),
            "tp1": _cell(x.tp1),
            "tp2": _cell(x.tp2),
            "tp3": _cell(x.tp3),
            "atr": _cell(x.atr),
            "btc_bias": x.btc_bias,
            "state": x.state,
            "outcome": x.outcome,
            "tp_hits": x.tp_hits,
            "fill_price": None if x.fill_price is None else _cell(x.fill_price),
            "gross_r": None if x.gross_r is None else _cell(x.gross_r),
            "net_r": None if x.net_r is None else _cell(x.net_r),
            "bars_held": x.bars_held,
            "closed_at": None if x.closed_at is None else _cell(x.closed_at),
        }

    @app.get(f"{r}/signals/trades", response_model=Envelope[SignalTradesData])
    def list_signal_trades(
        strategy: str | None = None,
        symbol: str | None = None,
        state: str | None = None,
        side: str | None = None,
        limit: int = 100,
        offset: int = 0,
        _: Principal = Depends(need(perm.VIEW)),
        s: Session = Depends(db),
    ):
        query = select(SignalTrade)
        if strategy:
            query = query.where(SignalTrade.strategy == strategy.strip().upper())
        if symbol:
            query = query.where(SignalTrade.symbol == symbol.strip().upper())
        if state:
            query = query.where(SignalTrade.state == state.strip().upper())
        if side:
            query = query.where(SignalTrade.side == side.strip().upper())
        total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = s.scalars(
            query.order_by(SignalTrade.issued_at.desc(), SignalTrade.symbol)
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        ).all()
        return envelope(
            {"total": total, "items": [_trade_row(x) for x in rows], "simulated": True},
            origin="PAPER",
        )

    @app.get(f"{r}/signals/trades/summary", response_model=Envelope[SignalTradeSummaryData])
    def signal_trade_summary(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        rows = s.scalars(select(SignalTrade)).all()
        return envelope(
            signals_summarize(
                [
                    SignalStatsRow(
                        x.strategy,
                        x.side,
                        x.score,
                        x.state,
                        x.outcome,
                        x.tp_hits,
                        None if x.net_r is None else float(x.net_r),
                        x.closed_at,
                    )
                    for x in rows
                ]
            ),
            origin="PAPER",
        )

    @app.get(f"{r}/signals/scans", response_model=Envelope[list[SignalScanModel]])
    def list_signal_scans(
        limit: int = 30, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        rows = s.scalars(
            select(SignalScan).order_by(SignalScan.started_at.desc()).limit(max(1, min(limit, 200)))
        ).all()
        return envelope([_scan_row(x) for x in rows], origin="PAPER")

    @app.get(f"{r}/signals/candidates", response_model=Envelope[SignalCandidatesData])
    def list_signal_candidates(
        meets: bool | None = None,
        symbol: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
        offset: int = 0,
        _: Principal = Depends(need(perm.VIEW)),
        s: Session = Depends(db),
    ):
        query = select(SignalCandidate)
        if meets is not None:
            query = query.where(SignalCandidate.meets_threshold.is_(meets))
        if symbol:
            query = query.where(SignalCandidate.symbol == symbol.strip().upper())
        if outcome:
            query = query.where(SignalCandidate.outcome == outcome.strip().upper())
        total = s.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = s.scalars(
            query.order_by(SignalCandidate.scored_at.desc(), SignalCandidate.symbol)
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        ).all()
        items = [
            {
                "id": str(x.id),
                "scan_id": str(x.scan_id),
                "symbol": x.symbol,
                "day": x.day,
                "scored_at": _cell(x.scored_at),
                "mode": x.mode,
                "eligible": x.eligible,
                "reason": x.reason,
                "score": _cell(x.score),
                "max_score": _cell(x.max_score),
                "score_ratio": _cell(x.score_ratio),
                "meets_threshold": x.meets_threshold,
                "outcome": x.outcome,
                "met": x.met or {},
                "not_met": x.not_met or {},
                "ai": x.ai,
                "levels": x.levels,
                "signal_id": x.signal_id,
            }
            for x in rows
        ]
        return envelope({"total": total, "items": items}, origin="PAPER")

    @app.get(f"{r}/signals/acks", response_model=Envelope[list[SignalAckModel]])
    def list_signal_acks(
        limit: int = 100, _: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)
    ):
        rows = s.scalars(
            select(SignalAckRow)
            .order_by(SignalAckRow.received_at.desc())
            .limit(max(1, min(limit, 500)))
        ).all()
        return envelope(
            [
                {
                    "id": str(x.id),
                    "signal_id": x.signal_id,
                    "stage": x.stage,
                    "environment": x.environment,
                    "status": x.status,
                    "reason": x.reason,
                    "received_at": _cell(x.received_at),
                }
                for x in rows
            ],
            origin="PAPER",
        )

    # ------------------------------------------------------------ credentials

    kinds = ("indodax", "telegram")

    def cred_store(s: Session) -> CredentialStore:
        store = ctx.credentials(s)
        if store is None:
            raise ApiError(
                503,
                "UNAVAILABLE",
                "master_key_unavailable",
                "the master key is not available, so credentials cannot be read or changed",
            )
        return store

    def cred_view(store: CredentialStore, kind: str) -> dict[str, Any]:
        info = store.describe(kind)
        if info is None:
            return {"kind": kind, "configured": False}
        return {
            "kind": kind,
            "configured": True,
            "hint": info["hint"],
            "created_at": _cell(info["created_at"]),
            "last_test_at": _cell(info["last_test_at"]) if info["last_test_at"] else None,
            "last_test_ok": info["last_test_ok"],
            "readable": store.readable(kind) is True,
        }

    def cred_check(kind: str, key: str, secret: str) -> tuple[bool, str | None]:
        """Test a candidate read-only. Never places or cancels an order."""
        if kind == "indodax":
            client = ctx.exchange_client_for(key, secret)
            if client is None:
                return False, "no exchange is configured, so the key cannot be tested"
            res = check_account(client)
            return res.ok, res.reason
        if ctx.telegram_send is None:
            return False, "no Telegram channel is available to test"
        try:
            ctx.telegram_send(key, secret, "AIDSS Trader: test message. Nothing needs doing.")
        except Exception:
            # The transport error can carry the URL, which contains the token: say nothing more.
            return False, "Telegram refused the message"
        return True, None

    def cred_valid(kind: str, body: CredentialBody) -> str | None:
        import re

        k, sec = body.key.strip(), body.secret.strip()
        if kind not in kinds:
            return "unknown credential kind"
        if kind == "indodax":
            ok = 8 <= len(k) <= 512 and 8 <= len(sec) <= 1024 and not re.search(r"\s", k + sec)
            return None if ok else "enter the API key and the secret exactly as Indodax shows them"
        ok = re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{20,}", k) and re.fullmatch(r"-?\d+|@\w{5,}", sec)
        return None if ok else "enter the bot token and the chat id"

    @app.get(f"{r}/credentials", response_model=Envelope[CredentialsData])
    def list_credentials(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        store = ctx.credentials(s)
        if store is None:
            return envelope({"available": False, "items": []})
        return envelope({"available": True, "items": [cred_view(store, k) for k in kinds]})

    @app.put(f"{r}/credentials/{{kind}}", response_model=Envelope[CredentialItemModel])
    def put_credential(
        kind: str,
        body: CredentialBody,
        who: Principal = Depends(need(perm.MANAGE_CREDENTIALS)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        if (why := cred_valid(kind, body)) is not None:
            raise ApiError(400, "VALIDATION", "bad_credential", why)
        step_up(s, who, "CREDENTIALS", x_step_up)
        key, secret = body.key.strip(), body.secret.strip()
        # Test first, store only on success: a rotation never leaves the Trader with no valid
        # key, and a key that can withdraw is never stored at all (ADR-013).
        ok, reason = cred_check(kind, key, secret)
        if not ok:
            AuditLogger(s).record(
                actor=who.user_id,
                action="credential.refused",
                subject_type="credential",
                subject_id=kind,
                after={"reason": reason},
            )
            s.commit()
            raise ApiError(422, "REJECTED", "credential_refused", reason or "the test failed")
        store = cred_store(s)
        store.put(kind, key=key, secret=secret)
        store.mark_test(kind, True)
        AuditLogger(s).record(
            actor=who.user_id,
            action="credential.store",
            subject_type="credential",
            subject_id=kind,
            after={"hint": cred_view(store, kind)["hint"]},
        )
        s.commit()
        ctx.notifier(s).emit("credential_changed", f"the {kind} credential changed", {"kind": kind})
        return envelope(cred_view(store, kind))

    @app.post(f"{r}/credentials/{{kind}}/test", response_model=Envelope[CredentialItemModel])
    def test_credential(
        kind: str,
        who: Principal = Depends(need(perm.MANAGE_CREDENTIALS)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        if kind not in kinds:
            raise ApiError(404, "NOT_FOUND", "unknown_kind", "no such credential kind")
        store = cred_store(s)
        try:
            found = store.get(kind)
        except CredentialUnreadable:
            raise ApiError(
                409,
                "CONFLICT",
                "credential_unreadable",
                "the stored credential cannot be decrypted; the master key changed. Enter it again",
            ) from None
        if found is None:
            raise ApiError(404, "NOT_FOUND", "no_credential", "no credential is stored")
        if kind == "indodax":
            client = ctx.stored_exchange_client()
            res = check_account(client) if client else None
            ok, reason = (res.ok, res.reason) if res else (False, "no exchange is configured")
        else:
            ok, reason = cred_check(kind, found[0], found[1])
        store.mark_test(kind, ok)
        AuditLogger(s).record(
            actor=who.user_id,
            action="credential.test",
            subject_type="credential",
            subject_id=kind,
            after={"ok": ok, "reason": reason},
        )
        s.commit()
        return envelope({**cred_view(store, kind), "reason": reason})

    @app.delete(f"{r}/credentials/{{kind}}", response_model=Envelope[CredentialItemModel])
    def delete_credential(
        kind: str,
        who: Principal = Depends(need(perm.MANAGE_CREDENTIALS)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        if kind not in kinds:
            raise ApiError(404, "NOT_FOUND", "unknown_kind", "no such credential kind")
        step_up(s, who, "CREDENTIALS", x_step_up)
        store = cred_store(s)
        if not store.remove(kind):
            raise ApiError(404, "NOT_FOUND", "no_credential", "no credential is stored")
        AuditLogger(s).record(
            actor=who.user_id,
            action="credential.remove",
            subject_type="credential",
            subject_id=kind,
        )
        s.commit()
        if kind == "indodax":
            # Without a key the Trader cannot trade, and it must say so (docs/05/13, "Remove").
            ctx.killswitch(s).activate("HALT", "owner", who.user_id)
        ctx.notifier(s).emit(
            "credential_changed", f"the {kind} credential was removed", {"kind": kind}
        )
        return envelope({"kind": kind, "configured": False})

    @app.get(f"{r}/paper-config", response_model=Envelope[PaperConfigData])
    def get_paper(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        ps = get_paper_settings(s)
        history = (
            s.scalar(select(func.count()).select_from(Fill).where(Fill.origin == "PAPER")) or 0
        )
        if ps is None:
            return envelope({"configured": False, "paper_fills": history}, origin="PAPER")
        c = ps.config
        plain = lambda v: format(v.normalize(), "f")  # noqa: E731
        return envelope(
            {
                "configured": True,
                "slippage_pct": plain(c.slippage_pct),
                "partial_fill_fraction": plain(c.partial_fill_fraction),
                "maker_fee_pct": plain(c.costs.maker_fee_pct),
                "taker_fee_pct": plain(c.costs.taker_fee_pct),
                "tax_pct": plain(c.costs.tax_pct),
                "clearing_pct": plain(c.costs.clearing_pct),
                "start_equity_idr": plain(ps.start_equity_idr),
                # Simulated fills already recorded keep the numbers they were made with.
                "paper_fills": history,
            },
            origin="PAPER",
        )

    @app.put(f"{r}/paper-config", response_model=Envelope[PutPaperData])
    def put_paper(
        body: PaperBody,
        who: Principal = Depends(need(perm.CONFIGURE_STRATEGY)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal, InvalidOperation

        try:
            values = {k: Decimal(v) for k, v in body.model_dump().items()}
            old = get_paper_settings(s)
            history = (
                s.scalar(select(func.count()).select_from(Fill).where(Fill.origin == "PAPER")) or 0
            )
            if old is not None and history > 0:
                # Making simulated results look better after they exist is the way paper evidence
                # gets quietly flattered, so it asks for the password like loosening a limit.
                trial = PaperSettings(
                    PaperConfig(
                        values["slippage_pct"],
                        values["partial_fill_fraction"],
                        CostModel(
                            values["maker_fee_pct"],
                            values["taker_fee_pct"],
                            values["tax_pct"],
                            values["clearing_pct"],
                        ),
                    ),
                    values["start_equity_idr"],
                )
                if paper_flatters(old, trial):
                    step_up(s, who, "RAISE_LIMIT", x_step_up)
            set_paper_settings(s, values, by=who.user_id)
        except (InvalidOperation, ValueError) as exc:
            raise ApiError(400, "VALIDATION", "bad_paper_config", str(exc)) from None
        s.commit()
        return envelope({"configured": True}, origin="PAPER")

    @app.get(f"{r}/promotion-thresholds", response_model=Envelope[PromotionThresholdsData])
    def get_thresholds(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cur = get_promotion_thresholds(s)
        raw = {k: _plain_limit(getattr(cur, k)) for k in THRESHOLD_FIELDS}
        if cur.min_paper_trades is not None:
            raw["min_paper_trades"] = cur.min_paper_trades
        unset = [k for k in THRESHOLD_FIELDS if getattr(cur, k) is None]
        return envelope({"thresholds": raw, "unset": unset})

    @app.put(f"{r}/promotion-thresholds", response_model=Envelope[PromotionThresholdsData])
    def put_thresholds(
        body: PromotionThresholdsBody,
        who: Principal = Depends(need(perm.PROMOTE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal, InvalidOperation

        old = get_promotion_thresholds(s)

        def _parse_dec(name: str, val: str | None) -> Decimal | None:
            if val is None or val == "":
                return None
            try:
                parsed = Decimal(str(val))
            except (InvalidOperation, ValueError):
                raise ApiError(400, "VALIDATION", "bad_value", f"bad value for {name}") from None
            if (problem := threshold_problem(name, parsed)) is not None:
                raise ApiError(400, "VALIDATION", "bad_value", f"{name}: {problem}")
            return parsed

        if body.min_paper_trades is not None:
            prob = threshold_problem("min_paper_trades", body.min_paper_trades)
            if prob is not None:
                raise ApiError(400, "VALIDATION", "bad_value", f"min_paper_trades: {prob}")
        new = Thresholds(
            min_paper_trades=body.min_paper_trades,
            max_paper_drawdown_pct=_parse_dec(
                "max_paper_drawdown_pct", body.max_paper_drawdown_pct
            ),
            backtest_min_return_pct=_parse_dec(
                "backtest_min_return_pct", body.backtest_min_return_pct
            ),
            max_live_capital_idr=_parse_dec("max_live_capital_idr", body.max_live_capital_idr),
            max_slippage_pct=_parse_dec("max_slippage_pct", body.max_slippage_pct),
        )
        if thresholds_loosen(old, new):
            step_up(s, who, "RAISE_LIMIT", x_step_up)
        set_promotion_thresholds(s, new, by=who.user_id)
        s.commit()
        ctx.notifier(s).emit(
            "limit_changed",
            "a promotion threshold changed",
            {"actor": who.user_id},
        )
        raw = {k: _plain_limit(getattr(new, k)) for k in THRESHOLD_FIELDS}
        if new.min_paper_trades is not None:
            raw["min_paper_trades"] = new.min_paper_trades
        unset = [k for k in THRESHOLD_FIELDS if getattr(new, k) is None]
        return envelope({"thresholds": raw, "unset": unset})

    def _origin_portfolio(s: Session, origin: Literal["LIVE", "PAPER"]) -> dict[str, Any]:
        positions, events = replay_origin(s, origin)
        realised = sum((e.pnl for e in events), ZERO)
        as_of, _ = ctx.freshness()
        loss_today = daily_loss(events, as_of)
        pos_items = []
        for pair in sorted(positions):
            pos = positions[pair]
            latest_intent = s.scalar(
                select(OrderIntentRow)
                .where(
                    OrderIntentRow.origin == origin,
                    OrderIntentRow.pair == pair,
                    OrderIntentRow.side == "BUY",
                )
                .order_by(OrderIntentRow.created_at.desc())
                .limit(1)
            )
            snap = (
                latest_intent.rule_snapshot
                if latest_intent and isinstance(latest_intent.rule_snapshot, dict)
                else {}
            )
            target = snap.get("target_price")
            pos_items.append(
                {
                    "origin": origin,
                    "pair": pair,
                    "quantity": _cell(pos.quantity),
                    "avg_cost": _cell(pos.avg_cost),
                    "cost_basis_idr": _cell(pos.quantity * pos.avg_cost),
                    "stop_price": (
                        None
                        if latest_intent is None or latest_intent.stop_price is None
                        else _cell(latest_intent.stop_price)
                    ),
                    "target_price": None if target is None else str(target),
                }
            )
        if origin == "LIVE":
            latest_eq = s.scalar(
                select(EquitySnapshot.equity_idr).order_by(EquitySnapshot.at.desc()).limit(1)
            )
            dd = None if latest_eq is None else drawdown_pct(s, latest_eq)
            return {
                "origin": "LIVE",
                "configured": True,
                "start_equity_idr": None,
                "latest_equity_idr": None if latest_eq is None else _cell(latest_eq),
                "realised_pnl_idr": _cell(realised),
                "daily_loss_idr": _cell(loss_today),
                "drawdown_pct": None if dd is None else _cell(dd),
                "trades_closed": len(events),
                "positions": pos_items,
            }
        ps = get_paper_settings(s)
        latest_peq = s.scalar(
            select(PaperEquitySnapshot.equity_idr).order_by(PaperEquitySnapshot.at.desc()).limit(1)
        )
        # With no snapshot yet, show cost-marked paper equity if paper is configured.
        if latest_peq is None and ps is not None:
            latest_peq = ps.start_equity_idr + realised
        earliest_at = datetime(1970, 1, 1, tzinfo=UTC)
        pdd = paper_drawdown_pct(s, earliest_at)
        return {
            "origin": "PAPER",
            "configured": ps is not None,
            "start_equity_idr": None if ps is None else _cell(ps.start_equity_idr),
            "latest_equity_idr": None if latest_peq is None else _cell(latest_peq),
            "realised_pnl_idr": _cell(realised),
            "daily_loss_idr": _cell(loss_today),
            "drawdown_pct": None if pdd is None else _cell(pdd),
            "trades_closed": len(events),
            "positions": pos_items,
        }

    @app.get(f"{r}/portfolio", response_model=Envelope[PortfolioData])
    def portfolio(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        bt_cols = (
            "id",
            "origin",
            "strategy_id",
            "strategy_version",
            "pair",
            "timeframe",
            "candles_used",
            "trades",
            "wins",
            "win_rate_pct",
            "total_return_pct",
            "max_drawdown_pct",
            "profit_factor",
            "start_equity_idr",
            "final_equity_idr",
            "data_fingerprint",
            "ran_at",
            "ran_by",
        )
        bt_query = select(BacktestRunRow).order_by(BacktestRunRow.ran_at.desc()).limit(50)
        bt_rows = [_row(b, bt_cols) for b in s.scalars(bt_query)]
        return envelope(
            {
                "live": _origin_portfolio(s, "LIVE"),
                "paper": _origin_portfolio(s, "PAPER"),
                "backtests": bt_rows,
            }
        )

    @app.post(f"{r}/events/{{event_id}}/ack", response_model=Envelope[AckData])
    def ack(
        event_id: str,
        who: Principal = Depends(need(perm.VIEW)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
    ):
        try:
            ev = ctx.notifier(s).acknowledge(uuid.UUID(event_id), who.user_id)
        except (KeyError, ValueError):
            raise ApiError(404, "NOT_FOUND", "unknown_event", "no such event") from None
        return envelope({"acked": ev.acked_at is not None})

    return app


_PCT = (
    "risk_per_trade_pct",
    "max_drawdown_pct",
    "max_exposure_per_pair_pct",
    "max_total_exposure_pct",
    "price_deviation_pct",
)
_POSITIVE_IDR = ("max_daily_loss_idr", "max_order_idr")
_POSITIVE_INT = (
    "max_consecutive_losses",
    "max_open_positions",
    "freshness_limit_s",
    "order_rate_limit",
)


def _plain_limit(v: Any) -> str | None:
    """A limit as the string the screen shows: no 18-digit padding from the database."""
    if v is None:
        return None
    return format(v.normalize(), "f") if hasattr(v, "as_tuple") else str(v)


def limit_problem(name: str, value: Any) -> str | None:
    """Why a limit value is not acceptable, or None. A `None` (unset) is always acceptable: it
    switches trading off, which is the safe direction. Ranges are checked here, not left to
    the form, because the API is the control (docs/04-UX-UI/00 principle 8)."""
    import re

    if value is None:
        return None
    if name in _PCT:
        return None if 0 < value <= 100 else "must be above 0 and at most 100"
    if name in _POSITIVE_IDR:
        return None if value > 0 else "must be above 0"
    if name in _POSITIVE_INT:
        return None if value >= 1 else "must be a whole number of at least 1"
    if name == "cooldown_s":
        return None if value >= 0 else "cannot be negative"
    if name == "daily_loss_day_boundary":
        return None if value == "LOCAL" else "only LOCAL (midnight WIB, ADR-034) is supported"
    if name == "trading_window":
        m = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", value)
        ok = m is not None and all(
            int(m[i]) < limit for i, limit in ((1, 24), (2, 60), (3, 24), (4, 60))
        )
        return None if ok else "use HH:MM-HH:MM"
    return None


def allowlist_loosens(old: Allowlist, new: Allowlist) -> bool:
    """True if `new` can trade something `old` could not: a new pair, ALL switched on or its number
    raised, a lower volume floor, a wider spread cap, or a liquidity filter switched on where it
    was not."""
    if set(new.pairs) - set(old.pairs):
        return True
    if new.all_pairs and (not old.all_pairs or (new.max_pairs or 0) > (old.max_pairs or 0)):
        # ALL switched on, or its number raised (an unset number counts as 0): more markets can
        # qualify. Turning ALL off, or lowering N, only narrows.
        return True
    a, b = old.liquidity, new.liquidity
    if not b.configured:
        return False
    if not a.configured:
        return True
    assert a.min_quote_volume_24h_idr is not None and b.min_quote_volume_24h_idr is not None
    assert a.max_spread_pct is not None and b.max_spread_pct is not None
    return (
        b.min_quote_volume_24h_idr < a.min_quote_volume_24h_idr
        or b.max_spread_pct > a.max_spread_pct
    )


# A higher value is looser for these; for the rest a lower value is looser.
_HIGHER_IS_LOOSER = (
    "risk_per_trade_pct",
    "max_daily_loss_idr",
    "max_drawdown_pct",
    "max_consecutive_losses",
    "max_open_positions",
    "max_exposure_per_pair_pct",
    "max_total_exposure_pct",
    "max_order_idr",
    "price_deviation_pct",
    "freshness_limit_s",
    "order_rate_limit",
)
_LOWER_IS_LOOSER = ("cooldown_s",)


def loosens(old: RiskLimits, new: RiskLimits) -> bool:
    """True if `new` lets more risk through than `old`. Setting a value where none was
    set also counts: it turns trading on, which is the loosest change there is."""
    for name in _HIGHER_IS_LOOSER + _LOWER_IS_LOOSER:
        a, b = getattr(old, name), getattr(new, name)
        if b is None:
            continue  # unsetting blocks trading: tighter
        if a is None:
            return True
        if (b > a) if name in _HIGHER_IS_LOOSER else (b < a):
            return True
    return False
