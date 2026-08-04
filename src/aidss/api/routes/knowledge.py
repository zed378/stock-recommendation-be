"""Knowledge base and news-schedule endpoints (Phase 7, Sections 6.3, 10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.agents.base import AgentRunner
from aidss.api.deps import get_db, require_permission
from aidss.api.schemas import (
    CronPresetResponse,
    KnowledgeDocumentCreate,
    KnowledgeDocumentResponse,
    NewsScheduleCreate,
    NewsScheduleResponse,
    RetrievalResponse,
    ScheduleRunResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import (
    Asset,
    KnowledgeBaseDocument,
    KnowledgeChunk,
    NewsItem,
    TickerNewsSchedule,
    User,
)
from aidss.llm.errors import GatewayError
from aidss.llm.provisioning import build_gateway
from aidss.news.collector import NewsCollector, NewsScheduler
from aidss.news.schedules import PRESETS, InvalidScheduleError, next_run_at, resolve
from aidss.plugins.registry import get_news_provider
from aidss.rag.engine import RAGEngine
from aidss.rag.provisioning import build_rag
from aidss.security.rbac import Permission

router = APIRouter(tags=["knowledge"])


def _rag(session: Session) -> RAGEngine:
    return build_rag(session)


# --- Knowledge base --------------------------------------------------------


@router.post(
    "/knowledge-base",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    payload: KnowledgeDocumentCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_PROVIDERS)),
) -> KnowledgeDocumentResponse:
    """Store and index a knowledge base document.

    Admin-only: the knowledge base shapes what every agent retrieves, so
    writing to it is a system-configuration action rather than a personal one.
    """
    document = KnowledgeBaseDocument(
        title=payload.title, source=payload.source, category=payload.category
    )
    session.add(document)
    session.flush()

    try:
        report = _rag(session).index_document(document, payload.content)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller below
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The document was not indexed because embedding failed: {exc}",
        ) from exc

    return KnowledgeDocumentResponse(
        id=document.id,
        title=document.title,
        source=document.source,
        category=document.category,
        chunks=report.chunks_created,
        uploaded_at=document.uploaded_at,
    )


@router.get("/knowledge-base", response_model=list[KnowledgeDocumentResponse])
def list_documents(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[KnowledgeDocumentResponse]:
    # One grouped count rather than a query per document: a knowledge base of
    # any size would otherwise make this endpoint N+1.
    counts = dict(
        session.execute(
            select(KnowledgeChunk.knowledge_base_id, func.count())
            .group_by(KnowledgeChunk.knowledge_base_id)
        ).all()
    )
    documents = session.scalars(
        select(KnowledgeBaseDocument).order_by(KnowledgeBaseDocument.uploaded_at.desc())
    ).all()
    return [
        KnowledgeDocumentResponse(
            id=d.id,
            title=d.title,
            source=d.source,
            category=d.category,
            chunks=counts.get(d.id, 0),
            uploaded_at=d.uploaded_at,
        )
        for d in documents
    ]


@router.get("/knowledge-base/search", response_model=RetrievalResponse)
def search_knowledge(
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=5, ge=1, le=25),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> RetrievalResponse:
    results = _rag(session).search_knowledge(q, limit=limit)
    return RetrievalResponse(query=q, results=[r.as_dict() for r in results])


@router.get("/assets/{ticker}/news/search", response_model=RetrievalResponse)
def search_news(
    ticker: str,
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=5, ge=1, le=25),
    window_days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> RetrievalResponse:
    asset = _resolve_asset(session, ticker)
    results = _rag(session).search_news(
        q, asset_id=asset.id, window_days=window_days, limit=limit
    )
    return RetrievalResponse(query=q, results=[r.as_dict() for r in results])


# --- News schedules (Section 6.3) -----------------------------------------


def _resolve_asset(session: Session, ticker: str, exchange: str = "IDX") -> Asset:
    asset = session.scalar(
        select(Asset).where(Asset.ticker == normalize_ticker(ticker), Asset.exchange == exchange)
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {ticker!r} is not registered",
        )
    return asset


def _to_response(schedule: TickerNewsSchedule, ticker: str) -> NewsScheduleResponse:
    return NewsScheduleResponse(
        id=schedule.id,
        ticker=ticker,
        cron_expression=schedule.cron_expression,
        preset_label=schedule.preset_label,
        is_active=schedule.is_active,
        status=schedule.status,
        consecutive_failures=schedule.consecutive_failures,
        last_fetched_at=schedule.last_fetched_at,
        next_run_at=schedule.next_run_at,
    )


@router.get("/news-schedules/presets", response_model=list[CronPresetResponse])
def list_presets(
    _: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[CronPresetResponse]:
    """The Section 6.3.4 presets, so a user need not write cron by hand."""
    return [
        CronPresetResponse(
            key=p.key, label=p.label, expression=p.expression, suited_to=p.suited_to
        )
        for p in PRESETS
    ]


@router.post(
    "/news-schedules", response_model=NewsScheduleResponse, status_code=status.HTTP_201_CREATED
)
def create_schedule(
    payload: NewsScheduleCreate,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> NewsScheduleResponse:
    asset = _resolve_asset(session, payload.ticker, payload.exchange)

    try:
        expression, preset_label = resolve(payload.preset, payload.cron_expression)
    except InvalidScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    existing = session.scalar(
        select(TickerNewsSchedule).where(
            TickerNewsSchedule.user_id == user.id,
            TickerNewsSchedule.asset_id == asset.id,
            TickerNewsSchedule.cron_expression == expression,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That schedule already exists for this asset",
        )

    schedule = TickerNewsSchedule(
        user_id=user.id,
        asset_id=asset.id,
        cron_expression=expression,
        preset_label=preset_label,
        next_run_at=next_run_at(expression),
    )
    session.add(schedule)
    session.flush()
    return _to_response(schedule, asset.ticker)


@router.get("/news-schedules", response_model=list[NewsScheduleResponse])
def list_schedules(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[NewsScheduleResponse]:
    rows = session.execute(
        select(TickerNewsSchedule, Asset)
        .join(Asset, Asset.id == TickerNewsSchedule.asset_id)
        .where(TickerNewsSchedule.user_id == user.id)
        .order_by(Asset.ticker)
    ).all()
    return [_to_response(schedule, asset.ticker) for schedule, asset in rows]


@router.delete("/news-schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    schedule = session.scalar(
        select(TickerNewsSchedule).where(
            TickerNewsSchedule.id == schedule_id, TickerNewsSchedule.user_id == user.id
        )
    )
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    session.delete(schedule)


@router.post("/news-schedules/{schedule_id}/run-now", response_model=ScheduleRunResponse)
def run_schedule_now(
    schedule_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.TRIGGER_INGESTION)),
) -> ScheduleRunResponse:
    """Run a schedule immediately, outside its cadence (Section 10).

    Uses the same code path as the scheduler, so a manual run exercises what
    the automated one will do rather than a convenient approximation.
    """
    schedule = session.scalar(
        select(TickerNewsSchedule).where(
            TickerNewsSchedule.id == schedule_id, TickerNewsSchedule.user_id == user.id
        )
    )
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    try:
        runner = AgentRunner(build_gateway(session))
    except GatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI layer is not available: {exc}",
        ) from exc

    collector = NewsCollector(
        session, get_news_provider(), runner=runner, rag=_rag(session)
    )
    report = NewsScheduler(session, collector).run_schedule(schedule, now=datetime.now(UTC))

    return ScheduleRunResponse(
        **report.as_dict(),
        status=schedule.status,
        next_run_at=schedule.next_run_at,
    )


@router.get("/assets/{ticker}/news", response_model=list[dict])
def list_news(
    ticker: str,
    limit: int = Query(default=25, ge=1, le=200),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[dict]:
    """Stored articles and their sentiment for one issuer (Section 10)."""
    from aidss.db.models import SentimentScore

    asset = _resolve_asset(session, ticker)
    items = session.scalars(
        select(NewsItem)
        .where(NewsItem.asset_id == asset.id)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    ).all()

    payload: list[dict] = []
    for item in items:
        score = session.scalar(
            select(SentimentScore)
            .where(SentimentScore.news_item_id == item.id)
            .order_by(SentimentScore.created_at.desc())
        )
        payload.append(
            {
                "headline": item.headline,
                "source": item.source,
                "source_url": item.source_url,
                "published_at": item.published_at.isoformat(),
                "summary": item.body_summary,
                "is_indexed": item.is_indexed,
                "sentiment": (
                    {"score": score.score, "rationale": score.rationale, "model": score.model_used}
                    if score
                    else None
                ),
            }
        )
    return payload
