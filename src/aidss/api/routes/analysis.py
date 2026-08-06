"""Multi-agent analysis endpoints (Phase 4, Section 10).

``POST`` runs the agents and stores the result; ``GET`` returns the most
recent stored run. Splitting them matters because a run costs real money -
re-reading an existing analysis should never trigger new model calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.engine import AnalysisEngine
from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.schemas import (
    AgentSkipResponse,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisUsageResponse,
    JobAcceptedResponse,
    RecommendationResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.db.models import AnalysisResult, Asset, User
from aidss.domain.types import Timeframe
from aidss.jobs.queue import enqueue
from aidss.llm.errors import GatewayError
from aidss.llm.provisioning import build_gateway
from aidss.security.rbac import Permission

router = APIRouter(prefix="/assets", tags=["analysis"], route_class=CommitBeforeResponse)

ANALYSIS_DISCLAIMER = (
    "AI-generated analysis for informational purposes only. It is not investment "
    "advice from a licensed adviser. Every figure it interprets was computed "
    "deterministically; the narrative around them is model-generated and should be "
    "weighed accordingly. All buy and sell decisions are yours, made outside this "
    "system - the platform has no ability to place an order."
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


@router.post("/{ticker}/analysis", response_model=AnalysisResponse)
def run_analysis(
    ticker: str,
    payload: AnalysisRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> AnalysisResponse:
    """Run the multi-agent flow over one asset and wait for it.

    Kept for scripts and for callers that genuinely want the result in the
    response, but the interface no longer uses it: a full run outlives the
    request timeout of anything sitting in front of the server, and behind a
    proxy that limit is not ours to raise. `POST .../analysis/background` is
    what the button calls.

    Translation is not done inline here either, for the same reason it is not
    done inline in the job: it doubles the time before the reader has anything,
    to render a language they may never switch to. The follow-up job is queued
    exactly as the background path queues it, so both routes leave the system
    in the same state.
    """
    asset = _resolve_asset(session, ticker, payload.exchange)

    try:
        engine = AnalysisEngine(session, build_gateway(session))
    except GatewayError as exc:
        # A misconfigured AI layer is a 503, not a 500: the request was fine,
        # the capability is not currently available.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI layer is not available: {exc}",
        ) from exc

    run = engine.analyze(
        asset,
        payload.timeframe,
        user_id=user.id,
        include_recommendation=payload.include_recommendation,
        translate_output=False,
    )

    if run.runs and run.analysis_result_id is not None:
        # Same follow-up the queued path enqueues, so one route does not quietly
        # produce a bilingual analysis while the other produces a monolingual
        # one. Deduplicated per analysis, so a caller that also queues it gets
        # the job that already exists.
        enqueue(
            session,
            "analysis.translate",
            {
                "analysis_result_id": str(run.analysis_result_id),
                "user_id": str(user.id),
                "ticker": run.asset_ticker,
            },
            dedup_key=f"translate:{run.analysis_result_id}",
        )

    if not run.runs:
        # Every agent skipped or failed. Reporting 200 with an empty body would
        # look like a successful analysis that happens to say nothing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "No agent produced output for this asset",
                "skipped": [{"agent": s.agent, "reason": s.reason} for s in run.skipped],
                "failed": [{"agent": f.agent, "reason": f.reason} for f in run.failed],
            },
        )

    return _to_response(run.asset_ticker, run.timeframe, run.analysis_result_id, run.as_payload())


@router.get("/{ticker}/analysis", response_model=AnalysisResponse)
def get_latest_analysis(
    ticker: str,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> AnalysisResponse:
    """Return the most recent stored analysis without calling any model."""
    asset = _resolve_asset(session, ticker, exchange)
    result = session.scalar(
        select(AnalysisResult)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(AnalysisResult.generated_at.desc())
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No analysis stored for {asset.ticker}; POST to this path to run one",
        )

    stored = (result.context_snapshot or {}).get("result", {})
    return _to_response(
        asset.ticker,
        Timeframe(stored.get("timeframe", Timeframe.D1.value)),
        result.id,
        stored,
    )


@router.get("/{ticker}/recommendation", response_model=RecommendationResponse)
def get_recommendation(
    ticker: str,
    exchange: str = Query(default="IDX"),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> RecommendationResponse:
    """The latest stored recommendation (Section 10).

    Read from the stored analysis payload rather than the ``recommendations``
    row, because the payload also carries the calibration breakdown and the
    method behind each price - the parts that make a score explainable rather
    than merely visible.
    """
    asset = _resolve_asset(session, ticker, exchange)
    result = session.scalar(
        select(AnalysisResult)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(AnalysisResult.generated_at.desc())
    )
    stored = ((result.context_snapshot if result else None) or {}).get("result", {})
    recommendation = stored.get("recommendation")

    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No recommendation stored for {asset.ticker}; "
                f"POST to /assets/{ticker}/analysis to produce one"
            ),
        )
    return RecommendationResponse(**recommendation)


def _to_response(
    ticker: str, timeframe: Timeframe, result_id: uuid.UUID | None, payload: dict
) -> AnalysisResponse:
    recommendation = payload.get("recommendation")
    return AnalysisResponse(
        ticker=ticker,
        timeframe=timeframe,
        analysis_result_id=result_id,
        recommendation=RecommendationResponse(**recommendation) if recommendation else None,
        agents=payload.get("agents", {}),
        skipped=[AgentSkipResponse(**s) for s in payload.get("skipped", [])],
        failed=[AgentSkipResponse(**f) for f in payload.get("failed", [])],
        usage=AnalysisUsageResponse(
            **payload.get("usage", {"total_tokens": 0, "estimated_cost": "0"})
        ),
        disclaimer=ANALYSIS_DISCLAIMER,
    )


@router.post(
    "/{ticker}/analysis/background",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_analysis(
    ticker: str,
    payload: AnalysisRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> JobAcceptedResponse:
    """Queue the analysis instead of running it on the request thread.

    Section 2.6 puts heavy work on the job queue. A full multi-agent run is
    several model calls; holding a connection open for it makes the request
    timeout the real limit on how thorough the analysis can be.

    Deduplicated per (asset, timeframe, minute): a double-click, or a retrying
    client, gets the job that already exists rather than a second run of the
    same work at full price.
    """
    asset = _resolve_asset(session, ticker, payload.exchange)
    minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")

    result = enqueue(
        session,
        "analysis.run",
        {
            "asset_id": str(asset.id),
            "timeframe": payload.timeframe.value,
            "user_id": str(user.id),
            "include_recommendation": payload.include_recommendation,
        },
        dedup_key=f"analysis:{asset.id}:{payload.timeframe.value}:{minute}",
    )

    return JobAcceptedResponse(
        job_id=result.job_id,
        job_type="analysis.run",
        deduplicated=result.deduplicated,
        poll_url=f"/jobs/{result.job_id}",
        note=(
            "An identical analysis was already queued; this returns that job."
            if result.deduplicated
            else "Queued. Poll the job for its result."
        ),
    )


@router.get("/{ticker}/analysis/history", response_model=list[uuid.UUID])
def list_analysis_history(
    ticker: str,
    exchange: str = Query(default="IDX"),
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[uuid.UUID]:
    asset = _resolve_asset(session, ticker, exchange)
    return list(
        session.scalars(
            select(AnalysisResult.id)
            .where(AnalysisResult.asset_id == asset.id)
            .order_by(AnalysisResult.generated_at.desc())
            .limit(limit)
        ).all()
    )
