"""Stock picks and monitoring (Sections 5.4, 9, 10).

Two surfaces that would be easy to build as a signal feed and are deliberately
not one:

  * **/stock-picks** returns a screen - assets meeting stated conditions, each
    carrying the conditions it met. Every response repeats that it is not a
    forecast, because a ranked list of tickers is read as one unless it says
    otherwise on the same screen.
  * **/alerts** returns observations. An alert says a level was crossed or a
    stance changed; what that means is decided on the analysis screen, where
    the confidence and the counter-evidence are.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.api.deps import get_db, require_permission
from aidss.api.schemas import (
    AlertResponse,
    QuoteSnapshotResponse,
    StockPickResponse,
    StrategyResponse,
    TranslationRequest,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import (
    Alert,
    AnalysisResult,
    Asset,
    Recommendation,
    User,
    Watchlist,
    WatchlistItem,
)
from aidss.llm.provisioning import build_gateway
from aidss.llm.router import Sensitivity
from aidss.monitoring.poller import latest_quotes, poll_watched_assets, recent_alerts
from aidss.plugins.registry import get_market_data_provider
from aidss.prompts.translation import translate
from aidss.recommendations.strategy import build_strategy
from aidss.screener import Horizon, screen
from aidss.security.rbac import Permission

router = APIRouter(tags=["market"])


# --- stock picks -----------------------------------------------------------


@router.get("/stock-picks", response_model=StockPickResponse)
def stock_picks(
    horizon: Horizon = Query(default=Horizon.D7),
    limit: int = Query(default=20, ge=1, le=100),
    min_score: float = Query(default=0.0, ge=0.0),
    watchlist_only: bool = Query(default=False),
    near_limit_only: bool = Query(
        default=False,
        description=(
            "Only assets that have consumed most of the session's upward "
            "auto-rejection band. Proximity is measured; it is not a prediction "
            "that the limit will be reached."
        ),
    ),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> StockPickResponse:
    """Rank stored assets by how many of the horizon's stated conditions they meet.

    Reads stored price history only. A screen that collected data would take
    minutes and would spend provider quota on assets nobody asked about.
    """
    asset_ids: list[uuid.UUID] | None = None
    if watchlist_only:
        asset_ids = [
            row[0]
            for row in session.execute(
                select(WatchlistItem.asset_id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(Watchlist.user_id == user.id)
                .distinct()
            ).all()
        ]

    result = screen(
        session,
        horizon,
        limit=limit,
        asset_ids=asset_ids,
        min_score=min_score,
        near_limit_only=near_limit_only,
    )
    return StockPickResponse(**result.as_dict())


# --- position-aware strategy ----------------------------------------------


@router.get("/assets/{ticker}/strategy", response_model=StrategyResponse)
def asset_strategy(
    ticker: str,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> StrategyResponse:
    """What the stored stance implies, read from both sides of a position.

    Both readings are returned regardless of what the caller actually holds.
    Seeing the case you are *not* in is what makes the asymmetry visible: an
    asset worth keeping but not worth buying today is a real and common
    situation, and returning only the reader's own side would hide it.
    """
    asset = session.scalar(
        select(Asset).where(
            Asset.ticker == normalize_ticker(ticker), Asset.exchange == exchange
        )
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {ticker!r} is not registered"
        )

    row = session.execute(
        select(Recommendation)
        .join(AnalysisResult, AnalysisResult.id == Recommendation.analysis_result_id)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No stored recommendation for {asset.ticker}. Run an analysis first - "
                "the strategy is derived from one, never produced independently."
            ),
        )

    recommendation = row[0]
    view = build_strategy(
        recommendation.label,
        recommendation.confidence,
        support_level=recommendation.support_level,
        resistance_level=recommendation.resistance_level,
        target_price=recommendation.target_price,
        suggested_stop=recommendation.suggested_stop,
    )
    payload = view.as_dict()
    payload["ticker"] = asset.ticker
    payload["as_of"] = recommendation.created_at
    return StrategyResponse(**payload)


# --- monitoring ------------------------------------------------------------


@router.post("/translate", response_model=dict)
def translate_payload(
    payload: TranslationRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict:
    """Render a stored analysis in the other language.

    A *rendering*, not a second analysis. Generating the analysis twice could
    produce two different stances for one asset with equal authority, and a
    reader seeing "beli" beside "hold" would have no way to resolve it. The
    original stays authoritative; this returns prose only, with the labels,
    prices, and confidence carried through untouched.
    """
    try:
        result = translate(
            build_gateway(session),
            payload.fields,
            payload.language,
            sensitivity=Sensitivity.SENSITIVE if payload.is_personal else Sensitivity.PUBLIC,
        )
    except ValueError as exc:
        # A partial or instruction-bearing translation is refused rather than
        # shown: half an analysis reads as a whole one that happens to be
        # missing its counter-evidence.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The translation could not be produced: {exc}",
        ) from exc
    return result.as_dict()


@router.get("/monitoring/quotes", response_model=list[QuoteSnapshotResponse])
def monitored_quotes(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[QuoteSnapshotResponse]:
    """The latest observation for every asset this user follows."""
    rows = session.execute(
        select(WatchlistItem.asset_id, Asset.ticker, Asset.exchange)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .join(Asset, Asset.id == WatchlistItem.asset_id)
        .where(Watchlist.user_id == user.id)
        .distinct()
    ).all()

    by_id = {asset_id: (ticker, exchange) for asset_id, ticker, exchange in rows}
    quotes = latest_quotes(session, list(by_id))

    responses: list[QuoteSnapshotResponse] = []
    for asset_id, (ticker, exchange) in sorted(by_id.items(), key=lambda kv: kv[1][0]):
        snapshot = quotes.get(asset_id)
        responses.append(
            QuoteSnapshotResponse(
                ticker=ticker,
                exchange=exchange,
                # None rather than a stale figure dressed as current: an asset
                # never polled has no observation, and inventing one from the
                # last daily bar would present yesterday's close as a quote.
                price=snapshot.price if snapshot else None,
                previous_close=snapshot.previous_close if snapshot else None,
                quoted_at=snapshot.quoted_at if snapshot else None,
                observed_at=snapshot.observed_at if snapshot else None,
                source=snapshot.source if snapshot else None,
                is_delayed=snapshot.is_delayed if snapshot else True,
            )
        )
    return responses


@router.post("/monitoring/poll", response_model=dict)
def poll_now(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> dict:
    """Observe this user's followed assets now, rather than waiting for the worker.

    Scoped to the caller's own watchlist: a manual poll is a person looking at
    their screen, and letting it sweep every asset in the system would let one
    user spend everyone's provider quota.
    """
    asset_ids = [
        row[0]
        for row in session.execute(
            select(WatchlistItem.asset_id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user.id)
            .distinct()
        ).all()
    ]
    report = poll_watched_assets(session, get_market_data_provider(), asset_ids=asset_ids)
    return report.as_dict()


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    unacknowledged_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[AlertResponse]:
    alerts = recent_alerts(
        session, user.id, limit=limit, unacknowledged_only=unacknowledged_only
    )
    tickers = {
        asset_id: ticker
        for asset_id, ticker in session.execute(
            select(Asset.id, Asset.ticker).where(
                Asset.id.in_([a.asset_id for a in alerts] or [uuid.uuid4()])
            )
        ).all()
    }
    return [
        AlertResponse(
            id=alert.id,
            ticker=tickers.get(alert.asset_id, "?"),
            kind=alert.kind,
            direction=alert.direction,
            message=alert.message,
            observed_price=alert.observed_price,
            reference_price=alert.reference_price,
            context=alert.context,
            triggered_at=alert.triggered_at,
            acknowledged_at=alert.acknowledged_at,
        )
        for alert in alerts
    ]


@router.post("/alerts/{alert_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
def acknowledge_alert(
    alert_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    alert = session.scalar(
        # Scoped by user id, so knowing an id is not enough to acknowledge
        # somebody else's alert.
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user.id)
    )
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert.acknowledged_at = datetime.now(UTC)
    session.flush()
