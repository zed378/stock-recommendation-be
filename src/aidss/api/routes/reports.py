"""Report, notification, and admin dashboard endpoints (Phase 8, Sections 9, 10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.schemas import (
    NotificationResponse,
    OperationsOverviewResponse,
    ReportResponse,
    UnreadCountResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import Asset, Portfolio, User
from aidss.reporting.builder import (
    ReportNotAvailable,
    build_asset_report,
    build_portfolio_report,
)
from aidss.reporting.notifications import NotificationService
from aidss.reporting.operations import build_overview
from aidss.security.rbac import Permission

router = APIRouter(tags=["reporting"], route_class=CommitBeforeResponse)


def _markdown(report) -> Response:
    """Serve the document itself when the caller asks for Markdown.

    A report is meant to be read, not only parsed, so the raw document is a
    first-class response rather than a string buried in JSON.
    """
    return Response(content=report.markdown, media_type="text/markdown; charset=utf-8")


@router.get("/assets/{ticker}/report")
def asset_report(
    ticker: str,
    exchange: str = Query(default="IDX"),
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
):
    """Compose a report from the stored analysis.

    Reads what was persisted rather than re-running agents: opening a report
    should not cost money, and one that regenerated itself would say something
    different each time, which makes it useless as a record.
    """
    asset = session.scalar(
        select(Asset).where(Asset.ticker == normalize_ticker(ticker), Asset.exchange == exchange)
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {ticker!r} is not registered"
        )

    try:
        report = build_asset_report(session, asset)
    except ReportNotAvailable as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if format == "markdown":
        return _markdown(report)
    return ReportResponse(
        title=report.title,
        generated_at=report.generated_at,
        markdown=report.markdown,
        payload=report.payload,
    )


@router.get("/portfolio/report")
def portfolio_report(
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
):
    portfolio = session.scalar(
        select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.name == "Default")
    )
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No portfolio exists yet"
        )

    try:
        report = build_portfolio_report(session, portfolio, user_id=user.id)
    except ReportNotAvailable as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if format == "markdown":
        return _markdown(report)
    return ReportResponse(
        title=report.title,
        generated_at=report.generated_at,
        markdown=report.markdown,
        payload=report.payload,
    )


# --- Notifications ---------------------------------------------------------


@router.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    #: Off by default so the existing "what's new" call is unchanged. The
    #: notification screen turns it on, because a list that empties itself as
    #: you read it cannot answer "what was that alert an hour ago?".
    include_read: bool = Query(default=False),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[NotificationResponse]:
    rows = NotificationService(session).recent(
        user.id, limit=limit, include_read=include_read
    )
    return [
        NotificationResponse(
            id=r.id,
            channel=r.channel,
            subject=r.subject,
            message=r.message,
            status=r.status,
            created_at=r.created_at,
            event=r.event,
            context=r.context,
        )
        for r in rows
    ]


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
def unread_notification_count(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> UnreadCountResponse:
    """Just the number, for the header badge.

    Separate from the list because the badge is polled and the list is not:
    fetching fifty rows every thirty seconds to render one integer is waste the
    indicator does not need to cause.
    """
    return UnreadCountResponse(unread=NotificationService(session).unread_count(user.id))


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    if not NotificationService(session).mark_read(user.id, notification_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )


# --- Admin dashboard -------------------------------------------------------


@router.get("/admin/overview", response_model=OperationsOverviewResponse)
def operations_overview(
    window_days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> OperationsOverviewResponse:
    """Is data flowing, is the AI layer working, what is it costing, what needs attention."""
    return OperationsOverviewResponse(**build_overview(session, window_days=window_days).as_dict())
