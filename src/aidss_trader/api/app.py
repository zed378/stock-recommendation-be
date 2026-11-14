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

import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.api import permissions as perm
from aidss_trader.approvals import ApprovalRefused, ApprovalWorkflow
from aidss_trader.auth.stepup import StepUp, StepUpRefused
from aidss_trader.auth.verify import AuthFailed, Principal, TokenVerifier
from aidss_trader.config import RiskLimits, load_risk_limits, save_risk_limits, unset_risk_fields
from aidss_trader.db.models import (
    ApprovalRow,
    AuditLog,
    LedgerEntry,
    OrderIntentRow,
    OrderRow,
    ReconciliationDifference,
    ReconciliationRun,
    StrategyRow,
    TradingEvent,
)
from aidss_trader.export import export_audit, export_ledger
from aidss_trader.intents.builder import Intent
from aidss_trader.killswitch import KillSwitch, KillSwitchRefused
from aidss_trader.notify import Notifier
from aidss_trader.promotion import Promotion, PromotionRefused, SuppliedEvidence, Thresholds

PREFIX = "/trader/v1"
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


class ApiError(Exception):
    def __init__(self, status: int, cls: str, code: str, message: str) -> None:
        self.status, self.cls, self.code, self.message = status, cls, code, message


def _meta(ctx: ApiContext, origin: str = "LIVE", source: str = "local") -> dict[str, Any]:
    as_of, stale = ctx.freshness()
    return {"source": source, "origin": origin, "as_of": as_of.isoformat(), "stale": stale}


def _row(obj: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in columns:
        v = getattr(obj, c)
        out[c] = (
            v.isoformat()
            if isinstance(v, datetime)
            else (str(v) if hasattr(v, "as_tuple") or isinstance(v, uuid.UUID) else v)
        )
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


class LimitsBody(BaseModel):
    limits: dict[str, str | int | None]


def create_app(ctx: ApiContext) -> FastAPI:
    app = FastAPI(title="AIDSS Trader API", docs_url=None, redoc_url=None)

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

    r = PREFIX

    # ----------------------------------------------------------------- reads

    @app.get(f"{r}/status")
    def status(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        state = ctx.killswitch(s).state()
        limits = load_risk_limits(s)
        modes = {x.strategy_id: x.mode for x in s.scalars(select(StrategyRow))}
        return envelope(
            {"trading_state": state, "unset_limits": unset_risk_fields(limits), "modes": modes}
        )

    @app.get(f"{r}/dashboard")
    def dashboard(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        live = [
            o
            for o in s.scalars(select(OrderRow).where(OrderRow.origin == "LIVE"))
            if o.state in {"OPEN", "PARTIALLY_FILLED", "CANCEL_REQUESTED", "UNKNOWN"}
        ]
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

    @app.get(f"{r}/strategies")
    def strategies(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        return envelope(
            [
                _row(x, ("strategy_id", "version", "mode", "since"))
                for x in s.scalars(select(StrategyRow))
            ],
            origin="PAPER",
        )

    @app.get(f"{r}/strategies/{{strategy_id}}/promotion")
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
                for g in Promotion(s).gates(strategy_id, nxt, ctx.thresholds(), SuppliedEvidence())
            ]
            if nxt
            else []
        )
        return envelope({"mode": row.mode, "next": nxt, "gates": gates})

    @app.get(f"{r}/intents")
    def intents(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cols = (
            "identity",
            "origin",
            "pair",
            "side",
            "entry_price",
            "quantity",
            "stop_price",
            "state",
            "created_at",
        )
        return envelope(
            [
                _row(i, cols)
                for i in s.scalars(
                    select(OrderIntentRow).order_by(OrderIntentRow.created_at.desc()).limit(200)
                )
            ]
        )

    @app.get(f"{r}/orders")
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

    @app.get(f"{r}/ledger")
    def ledger(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        return envelope(
            [
                _row(e, ("at", "origin", "entry_type", "asset", "amount", "reason"))
                for e in s.scalars(select(LedgerEntry).order_by(LedgerEntry.at.desc()).limit(500))
            ]
        )

    @app.get(f"{r}/events")
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

    @app.get(f"{r}/limits")
    def limits(_: Principal = Depends(need(perm.VIEW)), s: Session = Depends(db)):
        cur = load_risk_limits(s)
        data = (
            None
            if cur is None
            else {k: (None if v is None else str(v)) for k, v in asdict(cur).items()}
        )
        return envelope({"limits": data, "unset": unset_risk_fields(cur)})  # unset shown as null

    @app.get(f"{r}/reconciliation")
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

    @app.get(f"{r}/audit")
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

    @app.post(f"{r}/stepup")
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
        return Intent(
            identity=row.identity,
            strategy_version=row.strategy_version,
            pair=row.pair,
            side=row.side,
            entry_price=row.entry_price,
            quantity=row.quantity,
            stop_price=row.stop_price,
            risk_amount_idr=row.risk_amount_idr,
            rule_snapshot=row.rule_snapshot or {},
            mode="AUTO",  # approved: it may be sent
            signal_candle_open=row.created_at,
        )

    @app.post(f"{r}/intents/{{identity}}/approve")
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

    @app.post(f"{r}/intents/{{identity}}/deny")
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

    @app.post(f"{r}/strategies/{{strategy_id}}/promote")
    def promote(
        strategy_id: str,
        body: PromoteBody,
        who: Principal = Depends(need(perm.PROMOTE)),
        _k: str = Depends(idempotent),
        s: Session = Depends(db),
        x_step_up: str | None = Header(default=None),
    ):
        from decimal import Decimal

        row = s.get(StrategyRow, strategy_id)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "unknown_strategy", "no such strategy")
        needs_step = row.mode == "APPROVAL"  # the next mode is AUTO
        if needs_step:
            step_up(s, who, "PROMOTE_AUTO", x_step_up)

        def d(v: str | None):
            return None if v is None else Decimal(v)

        supplied = SuppliedEvidence(
            d(body.backtest_return_pct),
            d(body.paper_drawdown_pct),
            d(body.live_capital_used_idr),
            d(body.slippage_vs_paper_pct),
        )
        try:
            out = Promotion(s, ctx.notifier(s)).promote(
                strategy_id,
                who.user_id,
                ctx.thresholds(),
                supplied,
                body.note,
                step_up_ok=needs_step,
            )
        except PromotionRefused as exc:
            raise ApiError(409, "CONFLICT", "promotion_refused", str(exc)) from None
        return envelope({"mode": out.mode})

    @app.post(f"{r}/strategies/{{strategy_id}}/demote")
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

    @app.post(f"{r}/kill")
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

    @app.post(f"{r}/resume")
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

    @app.put(f"{r}/limits")
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
        current = load_risk_limits(s) or RiskLimits()
        new = RiskLimits(**{**asdict(current), **parsed})
        if loosens(current, new):
            step_up(s, who, "RAISE_LIMIT", x_step_up)
        version = save_risk_limits(s, new, set_by=who.user_id)
        s.commit()
        ctx.notifier(s).emit("limit_changed", "a risk limit changed", {"version": version})
        return envelope({"version": version, "unset": unset_risk_fields(new)})

    @app.post(f"{r}/events/{{event_id}}/ack")
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
