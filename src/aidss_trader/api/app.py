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
from aidss_trader.connector.errors import ConnectorError
from aidss_trader.connector.port import ExchangeClient
from aidss_trader.credentials import CredentialStore, CredentialUnreadable
from aidss_trader.credentials.admin import check_account
from aidss_trader.db.models import (
    ApprovalRow,
    AuditLog,
    BacktestRunRow,
    EquitySnapshot,
    Fill,
    IdempotencyRecord,
    LedgerEntry,
    OrderIntentRow,
    OrderRow,
    PaperEquitySnapshot,
    ReconciliationDifference,
    ReconciliationRun,
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
from aidss_trader.runtime.pair_selection import spread_pct as pair_spread_pct
from aidss_trader.runtime.settings_store import (
    MAX_ALL_PAIRS_LIMIT,
    MAX_HISTORY_BARS,
    THRESHOLD_FIELDS,
    Allowlist,
    LiquidityFilter,
    PaperSettings,
    StrategyDef,
    delete_strategy_def,
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
    set_strategy_params,
    threshold_problem,
    thresholds_loosen,
)
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


class StrategyBacktestData(BaseModel):
    strategy_id: str
    version: str | None
    pairs: list[BacktestPairModel]


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
                    SuppliedEvidence(paper_drawdown_pct=paper_drawdown_pct(s, row.since)),
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
        needs_step = row.mode == "APPROVAL"  # the next mode is AUTO
        if needs_step:
            step_up(s, who, "PROMOTE_AUTO", x_step_up)

        def d(v: str | None):
            return None if v is None else Decimal(v)

        # Paper drawdown is measured from the stored simulated equity, never typed in: a figure
        # the owner could edit before promoting would be no evidence at all.
        supplied = SuppliedEvidence(
            None,  # the backtest figure comes from stored runs (ADR-059), never from the caller
            paper_drawdown_pct(s, row.since),
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
            rows.sort(
                key=lambda x: (-Decimal(x["quote_volume_24h_idr"] or "0"), x["pair"])
            )
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
            raise ApiError(
                400, "VALIDATION", "bad_label", f"a name is 1 to {MAX_LABEL} characters"
            )
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
        for d in list_strategy_defs(s):
            version, error = _def_version(d)
            rows = [] if version is None else _latest_rows(s, d.id, version)
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
        set_strategy_def(
            s, StrategyDef(strategy_id, existing.kind, label, dict(body.params)), by=who.user_id
        )
        s.commit()
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
                    "this strategy has an open position or an unfinished order; "
                    "close it first",
                )
        delete_strategy_def(s, strategy_id, by=who.user_id)
        s.commit()
        return envelope({"deleted": True}, origin="PAPER")

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
        picked = [
            (sid, (lambda d=defs[sid]: build_strategy(d.kind, d.params))) for sid in wanted
        ]
        job = jobs.start(picked, by=f"user:{who.user_id}")
        return envelope(_job_data(job), origin="BACKTEST")

    @app.get(f"{r}/backtests/{{job_id}}", response_model=Envelope[BacktestJobData])
    def backtest_job(job_id: str, _: Principal = Depends(need(perm.VIEW))):
        job = jobs.get(job_id)
        if job is None:
            raise ApiError(404, "NOT_FOUND", "unknown_job", "no such backtest job")
        return envelope(_job_data(job), origin="BACKTEST")

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
            select(PaperEquitySnapshot.equity_idr)
            .order_by(PaperEquitySnapshot.at.desc())
            .limit(1)
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
