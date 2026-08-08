"""Portfolio endpoints (Section 8).

Every position here is entered by the user (``input_method``). There is no
broker synchronisation, and the schema has no value that would represent one -
see the ``HoldingInputMethod`` enum.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.schemas import (
    AgentSkipResponse,
    HoldingResponse,
    HoldingUpsert,
    PortfolioAnalysisResponse,
    PortfolioResponse,
    SimulationRequest,
    SimulationResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import Asset, Portfolio, PortfolioAnalysis, PortfolioHolding, User
from aidss.llm.errors import GatewayError
from aidss.llm.gateway import LLMGateway
from aidss.llm.provisioning import build_gateway
from aidss.llm.router import ModelRouter
from aidss.portfolio.engine import PortfolioIntelligenceEngine
from aidss.portfolio.loader import load_positions, load_price_series
from aidss.portfolio.simulation import AllocationChange, SimulationError, simulate
from aidss.security.rbac import Permission

router = APIRouter(prefix="/portfolio", tags=["portfolio"], route_class=CommitBeforeResponse)

PORTFOLIO_DISCLAIMER = (
    "Computed from holdings you entered yourself. Concentration, diversification, "
    "correlation, and risk figures are deterministic; any narrative around them is "
    "AI-generated. Every risk figure is historical - it describes what has happened, "
    "not what will. This is not investment advice from a licensed adviser, and the "
    "platform cannot place an order."
)


def _null_gateway() -> LLMGateway:
    """A gateway with no providers, for paths that must not call a model.

    Passing one makes the intent explicit and enforceable: if a code path ever
    tries to run an agent from a GET, routing raises rather than quietly
    spending money.
    """
    return LLMGateway(ModelRouter([]))


def _default_portfolio(session: Session, user: User) -> Portfolio:
    portfolio = session.scalar(
        select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.name == "Default")
    )
    if portfolio is None:
        portfolio = Portfolio(user_id=user.id, name="Default")
        session.add(portfolio)
        session.flush()
    return portfolio


def _holdings(session: Session, portfolio: Portfolio) -> list[HoldingResponse]:
    rows = session.execute(
        select(PortfolioHolding, Asset)
        .join(Asset, Asset.id == PortfolioHolding.asset_id)
        .where(PortfolioHolding.portfolio_id == portfolio.id)
        .order_by(Asset.ticker)
    ).all()
    return [
        HoldingResponse(
            id=holding.id,
            ticker=asset.ticker,
            exchange=asset.exchange,
            quantity=holding.quantity,
            average_price=holding.average_price,
            input_method=holding.input_method,
            updated_at=holding.updated_at,
        )
        for holding, asset in rows
    ]


@router.get("", response_model=PortfolioResponse)
def get_portfolio(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> PortfolioResponse:
    portfolio = _default_portfolio(session, user)
    return PortfolioResponse(
        id=portfolio.id,
        name=portfolio.name,
        base_currency=portfolio.base_currency,
        holdings=_holdings(session, portfolio),
    )


@router.post("/holdings", response_model=PortfolioResponse)
def upsert_holding(
    payload: HoldingUpsert,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> PortfolioResponse:
    ticker = normalize_ticker(payload.ticker)
    asset = session.scalar(
        select(Asset).where(Asset.ticker == ticker, Asset.exchange == payload.exchange)
    )
    if asset is None:
        asset = Asset(ticker=ticker, exchange=payload.exchange)
        session.add(asset)
        session.flush()

    portfolio = _default_portfolio(session, user)
    holding = session.scalar(
        select(PortfolioHolding).where(
            PortfolioHolding.portfolio_id == portfolio.id,
            PortfolioHolding.asset_id == asset.id,
        )
    )
    if holding is None:
        session.add(
            PortfolioHolding(
                portfolio_id=portfolio.id,
                asset_id=asset.id,
                quantity=payload.quantity,
                average_price=payload.average_price,
                input_method=payload.input_method,
            )
        )
    else:
        holding.quantity = payload.quantity
        holding.average_price = payload.average_price
        holding.input_method = payload.input_method
    session.flush()

    return PortfolioResponse(
        id=portfolio.id,
        name=portfolio.name,
        base_currency=portfolio.base_currency,
        holdings=_holdings(session, portfolio),
    )


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(
    holding_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    portfolio = _default_portfolio(session, user)
    holding = session.scalar(
        select(PortfolioHolding).where(
            PortfolioHolding.id == holding_id,
            PortfolioHolding.portfolio_id == portfolio.id,
        )
    )
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    session.delete(holding)


# --- Portfolio intelligence (Phase 6) --------------------------------------


@router.post("/analysis", response_model=PortfolioAnalysisResponse)
def run_portfolio_analysis(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> PortfolioAnalysisResponse:
    """Evaluate diversification, concentration, and historical risk."""
    portfolio = _default_portfolio(session, user)

    try:
        engine = PortfolioIntelligenceEngine(session, build_gateway(session))
    except GatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI layer is not available: {exc}",
        ) from exc

    run = engine.analyze(portfolio, user_id=user.id)
    payload = run.as_payload()
    return PortfolioAnalysisResponse(
        portfolio=payload["portfolio"],
        metrics=payload["metrics"],
        risk=payload["risk"],
        correlation=payload["correlation"],
        holdings=payload["holdings"],
        agents=payload["agents"],
        skipped=[AgentSkipResponse(**s) for s in payload["skipped"]],
        failed=[AgentSkipResponse(**f) for f in payload["failed"]],
        disclaimer=PORTFOLIO_DISCLAIMER,
    )


@router.get("/analysis", response_model=PortfolioAnalysisResponse)
def get_portfolio_analysis(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> PortfolioAnalysisResponse:
    """Recompute the deterministic figures without calling any model.

    The metrics are cheap arithmetic, so they are always current here; only the
    narrative costs money, and a GET does not buy one. Whatever narrative the
    last run produced is returned alongside.
    """
    portfolio = _default_portfolio(session, user)
    engine = PortfolioIntelligenceEngine(session, _null_gateway())
    context = engine.build_context(portfolio, user.id)

    stored = session.scalar(
        select(PortfolioAnalysis)
        .where(PortfolioAnalysis.portfolio_id == portfolio.id)
        .order_by(PortfolioAnalysis.simulated_at.desc())
    )
    agents = (
        {"portfolio_analyzer": {"summary": stored.narrative}}
        if stored is not None and stored.narrative
        else {}
    )

    return PortfolioAnalysisResponse(
        portfolio=portfolio.name,
        metrics=context.metrics.as_dict() if context.metrics else {},
        risk=context.risk.as_dict() if context.risk else {},
        correlation=context.correlation,
        holdings=context.holdings_payload(),
        agents=agents,
        skipped=[],
        failed=[],
        disclaimer=PORTFOLIO_DISCLAIMER,
    )


@router.post("/simulate", response_model=SimulationResponse)
def simulate_allocation(
    payload: SimulationRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> SimulationResponse:
    """Compare the portfolio against a hypothetical version of itself.

    Read-only in the strongest sense: no holding is written, no order exists to
    place, and the stored portfolio is identical before and after the call.
    """
    portfolio = _default_portfolio(session, user)
    positions = load_positions(session, portfolio)
    series = load_price_series(session, positions)

    try:
        result = simulate(
            positions,
            [
                AllocationChange(ticker=normalize_ticker(c.ticker), quantity=c.quantity)
                for c in payload.changes
            ],
            series,
        )
    except SimulationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    body = result.as_dict()
    return SimulationResponse(**body, disclaimer=PORTFOLIO_DISCLAIMER)
