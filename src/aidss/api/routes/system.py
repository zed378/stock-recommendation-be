"""Health check and provider inventory endpoints (Section 8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.schemas import BudgetStatusResponse, ProviderInventoryResponse
from aidss.config import Settings, get_settings
from aidss.db.models import User
from aidss.observability.budget import daily_status
from aidss.observability.metrics import registry
from aidss.plugins.registry import registry_snapshot
from aidss.security.rbac import Permission

router = APIRouter(tags=["system"], route_class=CommitBeforeResponse)


@router.get("/health")
def health(session: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "environment": settings.environment,
        "database": "ok" if database_ok else "unreachable",
    }


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus exposition (Phase 9, Section 2.6).

    Unauthenticated by design and excluded from rate limiting: a scraper that
    needs a token is a scraper that stops working when auth breaks, which is
    exactly when the metrics matter. Nothing here is sensitive - counts,
    latencies, and route templates, never payloads or identifiers.

    Restrict it at the network layer in production; that is where this kind of
    access control belongs.
    """
    return Response(
        content=registry().render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/admin/budget", response_model=BudgetStatusResponse)
def budget_status(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> BudgetStatusResponse:
    """Where AI spend stands against the configured daily ceiling (Section 16.9)."""
    status = daily_status(
        session,
        ceiling=settings.daily_ai_budget,
        warning_threshold=settings.budget_warning_threshold,
    )
    return BudgetStatusResponse(**status.as_dict())


@router.get("/providers", response_model=ProviderInventoryResponse)
def list_providers(
    settings: Settings = Depends(get_settings),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> ProviderInventoryResponse:
    """Which adapters are registered, and which one is currently selected.

    Swapping a provider is a configuration change, never a code change
    (Section 5, FR-07) - this endpoint exists so an admin can see both halves.
    """
    return ProviderInventoryResponse(
        registered=registry_snapshot(),
        active={
            "market_data": settings.market_data_provider,
            "news": settings.news_provider,
            "ai": settings.ai_provider,
            "storage": settings.storage_provider,
        },
    )
