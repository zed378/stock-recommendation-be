"""Asset, market data ingestion, and indicator endpoints (Section 10).

Note what is absent here and must stay absent: there is no ``/orders``,
``/execute``, or any other endpoint capable of sending an instruction to a
broker. That absence is an architectural hard constraint (Section 3, 4, 10),
not a feature scheduled for later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.schemas import (
    AssetCreate,
    AssetResponse,
    CandleResponse,
    FundamentalIngestResponse,
    FundamentalMetricResponse,
    IndicatorSnapshotResponse,
    IngestRequest,
    IngestResponse,
)
from aidss.collectors.market_data import (
    FundamentalCollector,
    MarketDataCollector,
    load_candles,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import Asset, FundamentalMetric, User
from aidss.domain.types import Timeframe
from aidss.indicators.engine import IndicatorEngine
from aidss.indicators.features import compute_features, persist_features
from aidss.plugins.errors import ProviderUnavailableError
from aidss.plugins.registry import get_market_data_provider
from aidss.security.rbac import Permission

router = APIRouter(prefix="/assets", tags=["assets"], route_class=CommitBeforeResponse)

DISCLAIMER = (
    "Deterministically computed indicators and features for informational "
    "purposes only. This is not investment advice from a licensed adviser, and "
    "the platform never places orders on your behalf."
)


def _resolve_asset(session: Session, ticker: str, exchange: str) -> Asset:
    asset = session.scalar(
        select(Asset).where(Asset.ticker == normalize_ticker(ticker), Asset.exchange == exchange)
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset {ticker!r} on exchange {exchange!r} is not registered",
        )
    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_MARKET_DATA)),
) -> list[Asset]:
    return list(session.scalars(select(Asset).order_by(Asset.ticker)).all())


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreate,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> Asset:
    ticker = normalize_ticker(payload.ticker)
    existing = session.scalar(
        select(Asset).where(Asset.ticker == ticker, Asset.exchange == payload.exchange)
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset already exists")

    asset = Asset(**{**payload.model_dump(), "ticker": ticker})
    session.add(asset)
    session.flush()
    return asset


@router.post("/{ticker}/ingest", response_model=IngestResponse)
def ingest_market_data(
    ticker: str,
    payload: IngestRequest,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.TRIGGER_INGESTION)),
) -> IngestResponse:
    """Run the Phase 2 + Phase 3 pipeline for one asset, synchronously.

    Synchronous execution is fine for a single asset over a bounded range.
    Bulk backfills belong on the job queue (Section 2.6, Asynchronous
    Processing) rather than on a request thread.
    """
    collector = MarketDataCollector(get_market_data_provider())
    asset = collector.get_or_create_asset(session, ticker, exchange=exchange)

    end = datetime.now(UTC)
    start = end - timedelta(days=payload.days)

    try:
        report = collector.collect(session, asset, payload.timeframe, start, end)
    except ProviderUnavailableError as exc:
        # 502 rather than 500: the failure is upstream, and `retryable` tells
        # the caller whether trying again is worthwhile.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "retryable": exc.retryable},
        ) from exc

    candles = load_candles(session, asset.id, payload.timeframe)
    indicator_report = IndicatorEngine().persist(session, asset.id, payload.timeframe, candles)
    persist_features(session, asset.id, payload.timeframe, candles)

    return IngestResponse(
        ticker=asset.ticker,
        timeframe=payload.timeframe,
        provider=report.provider,
        fetched=report.fetched,
        inserted=report.inserted,
        updated=report.updated,
        rejected=report.rejected,
        rejection_reasons=report.rejection_reasons or [],
        indicators_inserted=indicator_report.inserted,
        indicators_updated=indicator_report.updated,
    )


@router.post("/{ticker}/fundamentals/ingest", response_model=FundamentalIngestResponse)
def ingest_fundamentals(
    ticker: str,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.TRIGGER_INGESTION)),
) -> FundamentalIngestResponse:
    """Fetch reported financial metrics for one issuer.

    Separate from the price ingest because the cadences differ: prices change
    every session, fundamentals every quarter. Running them together would mean
    either fetching fundamentals far too often or prices far too rarely.
    """
    collector = FundamentalCollector(get_market_data_provider())
    asset = MarketDataCollector(get_market_data_provider()).get_or_create_asset(
        session, ticker, exchange=exchange
    )

    try:
        report = collector.collect(session, asset)
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "retryable": exc.retryable},
        ) from exc

    return FundamentalIngestResponse(
        ticker=report.ticker,
        fetched=report.fetched,
        inserted=report.inserted,
        updated=report.updated,
        unsupported=report.unsupported,
        note=(
            "The active market data provider publishes no fundamental data for this "
            "issuer. The Fundamental Analyzer will continue to report insufficient "
            "coverage, which is the accurate result."
            if report.unsupported
            else f"{report.fetched} metrics stored."
        ),
    )


@router.get("/{ticker}/fundamentals", response_model=list[FundamentalMetricResponse])
def list_fundamentals(
    ticker: str,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_MARKET_DATA)),
) -> list[FundamentalMetricResponse]:
    asset = _resolve_asset(session, ticker, exchange)
    rows = session.scalars(
        select(FundamentalMetric)
        .where(FundamentalMetric.asset_id == asset.id)
        .order_by(FundamentalMetric.period.desc(), FundamentalMetric.metric_name)
    ).all()
    return [
        FundamentalMetricResponse(
            metric=row.metric_name,
            period=row.period,
            period_type=row.period_type,
            value=row.value,
            source=row.source,
        )
        for row in rows
    ]


@router.get("/{ticker}/candles", response_model=list[CandleResponse])
def get_candles(
    ticker: str,
    timeframe: Timeframe = Query(default=Timeframe.D1),
    exchange: str = Query(default="IDX"),
    limit: int = Query(default=200, ge=1, le=5000),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_MARKET_DATA)),
) -> list[CandleResponse]:
    asset = _resolve_asset(session, ticker, exchange)
    candles = load_candles(session, asset.id, timeframe, limit=limit)
    # Candle is a slotted dataclass, so it has no __dict__ to unpack from.
    return [
        CandleResponse(
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles
    ]


@router.get("/{ticker}/indicators", response_model=IndicatorSnapshotResponse)
def get_indicator_snapshot(
    ticker: str,
    timeframe: Timeframe = Query(default=Timeframe.D1),
    exchange: str = Query(default="IDX"),
    lookback: int = Query(default=400, ge=60, le=5000),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_MARKET_DATA)),
) -> IndicatorSnapshotResponse:
    """Current indicator values plus derived features.

    This payload is the exact shape the Context Builder will consume in
    Phase 4: every number here is already settled, so the AI layer only has to
    interpret it rather than compute it (Section 2.7, 5.3).
    """
    asset = _resolve_asset(session, ticker, exchange)
    candles = load_candles(session, asset.id, timeframe, limit=lookback)
    if not candles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No price data stored for {asset.ticker}; run /assets/{ticker}/ingest first",
        )

    return IndicatorSnapshotResponse(
        ticker=asset.ticker,
        timeframe=timeframe,
        snapshot=IndicatorEngine().snapshot(candles),
        features=compute_features(candles),
        disclaimer=DISCLAIMER,
    )
