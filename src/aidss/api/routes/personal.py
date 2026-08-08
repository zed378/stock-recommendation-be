"""Preferences, the issuer calendar, sharing, and chart evidence.

Four surfaces that arrived together and are grouped by who they belong to:
each is about one account's own relationship to the platform rather than about
market data. None of them introduces an instruction-shaped output, and the two
that come closest - a calendar of dated events and an analysis sent to another
person - carry their guards in the service layer rather than here.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.memory import DEFAULT_PREFERENCES, MemoryManager, PreferenceKey
from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.collab import sharing
from aidss.db.models import (
    AnalysisResult,
    Asset,
    ShareKind,
    User,
    Watchlist,
    WatchlistItem,
)
from aidss.domain.types import Timeframe
from aidss.monitoring.agenda import upcoming
from aidss.recommendations.evidence import for_recommendation
from aidss.security.rbac import Permission

router = APIRouter(tags=["personal"], route_class=CommitBeforeResponse)


# --- investor profile -------------------------------------------------------


#: Closed vocabularies rather than free strings. Each value is looked up in a
#: framing table when the prompt is built (`prompts/framing.py`); an unknown
#: value would silently produce no framing at all, which looks identical to
#: never having set a preference.
Horizon = Literal["short", "medium", "long"]
RiskAppetite = Literal["conservative", "moderate", "aggressive"]
Experience = Literal["beginner", "intermediate", "advanced"]
Depth = Literal["brief", "standard", "detailed"]
Privacy = Literal["standard", "high"]


class PreferencesResponse(BaseModel):
    #: The same closed sets the update accepts, so a client cannot be typed
    #: against `str` on the way in and a union on the way out.
    investment_horizon: Horizon
    risk_appetite: RiskAppetite
    experience_level: Experience
    explanation_depth: Depth
    privacy_mode: Privacy
    #: Which of these the investor actually said, as opposed to defaults the
    #: platform is standing in with. The Memory Manager already distinguishes
    #: stated from inferred; reporting it keeps the interface from showing a
    #: default back as though it were a choice.
    stated: list[str]


class PreferencesUpdate(BaseModel):
    investment_horizon: Horizon | None = None
    risk_appetite: RiskAppetite | None = None
    experience_level: Experience | None = None
    explanation_depth: Depth | None = None
    privacy_mode: Privacy | None = None


_KEYS = {
    "investment_horizon": PreferenceKey.HORIZON,
    "risk_appetite": PreferenceKey.RISK_APPETITE,
    "experience_level": PreferenceKey.EXPERIENCE,
    "explanation_depth": PreferenceKey.EXPLANATION_DEPTH,
    "privacy_mode": PreferenceKey.PRIVACY_MODE,
}


#: Permitted values per field, used to clamp what is read back.
_ALLOWED: dict[str, tuple[str, ...]] = {
    "investment_horizon": ("short", "medium", "long"),
    "risk_appetite": ("conservative", "moderate", "aggressive"),
    "experience_level": ("beginner", "intermediate", "advanced"),
    "explanation_depth": ("brief", "standard", "detailed"),
    "privacy_mode": ("standard", "high"),
}


def _clamp(field_name: str, value: Any) -> str:
    """A stored value outside the closed set falls back to the default.

    The preference store is a JSON column with no constraint, so a value
    written by an older build - or by hand - can be anything. Returned as-is it
    would fail response validation and turn a settings page into a 500; passed
    to the framing table it would silently match nothing. Falling back is the
    only outcome that leaves both working.
    """
    text = str(value)
    allowed = _ALLOWED[field_name]
    return text if text in allowed else str(DEFAULT_PREFERENCES[_KEYS[field_name]])


def _preferences(session: Session, user: User) -> PreferencesResponse:
    from aidss.db.models import UserPreference

    memory = MemoryManager(session).load(user.id)
    stated = [
        row.key
        for row in session.scalars(
            select(UserPreference).where(
                UserPreference.user_id == user.id, UserPreference.source == "stated"
            )
        ).all()
    ]
    return PreferencesResponse(
        investment_horizon=_clamp("investment_horizon", memory.horizon),
        risk_appetite=_clamp("risk_appetite", memory.risk_appetite),
        experience_level=_clamp(
            "experience_level", memory.preferences.get(PreferenceKey.EXPERIENCE)
        ),
        explanation_depth=_clamp(
            "explanation_depth", memory.preferences.get(PreferenceKey.EXPLANATION_DEPTH)
        ),
        privacy_mode=_clamp("privacy_mode", memory.preferences.get(PreferenceKey.PRIVACY_MODE)),
        stated=sorted(stated),
    )


@router.get("/me/preferences", response_model=PreferencesResponse)
def read_preferences(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> PreferencesResponse:
    """How this investor has said they invest.

    Defaults are returned for anything unset, and `stated` names which ones are
    real answers - the difference matters, because an inferred or defaulted
    preference must never be reflected back as something the investor told us.
    """
    return _preferences(session, user)


@router.patch("/me/preferences", response_model=PreferencesResponse)
def update_preferences(
    payload: PreferencesUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> PreferencesResponse:
    """Set one or more preferences. Only the fields sent are touched.

    Partial for the same reason the provider PATCH is: a form that saves one
    field must not quietly reset the four beside it.
    """
    manager = MemoryManager(session)
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if value is None:
            continue
        manager.remember(user.id, _KEYS[field_name], value, source="stated")
    return _preferences(session, user)


@router.get("/me/preferences/options", response_model=dict)
def preference_options() -> dict[str, Any]:
    """The permitted values, so the interface does not hardcode a second copy."""
    return {
        "investment_horizon": ["short", "medium", "long"],
        "risk_appetite": ["conservative", "moderate", "aggressive"],
        "experience_level": ["beginner", "intermediate", "advanced"],
        "explanation_depth": ["brief", "standard", "detailed"],
        "privacy_mode": ["standard", "high"],
        "defaults": dict(DEFAULT_PREFERENCES),
    }


# --- issuer calendar --------------------------------------------------------


class AgendaItemResponse(BaseModel):
    ticker: str
    kind: str
    scheduled_for: date
    title: str
    detail: str | None
    source: str
    source_url: str | None


class AgendaPage(BaseModel):
    items: list[AgendaItemResponse]
    total: int
    caveat: str


AGENDA_CAVEAT = (
    "Scheduled dates as disclosed, nothing more. This calendar states when "
    "something is planned; it holds no view on what any event will do to a "
    "price. Dates sourced from coverage rather than the exchange are marked as "
    "such and can move."
)


@router.get("/agenda", response_model=AgendaPage)
def read_agenda(
    watchlist_only: bool = Query(default=False),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> AgendaPage:
    """Dated events ahead, nearest first."""
    tickers: list[str] | None = None
    if watchlist_only:
        tickers = [
            row[0]
            for row in session.execute(
                select(Asset.ticker)
                .join(WatchlistItem, WatchlistItem.asset_id == Asset.id)
                .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
                .where(Watchlist.user_id == user.id)
                .distinct()
            ).all()
        ]

    rows, total = upcoming(
        session, tickers=tickers, days=days, limit=limit, offset=offset
    )
    return AgendaPage(
        items=[
            AgendaItemResponse(
                ticker=row.ticker,
                kind=row.kind.value,
                scheduled_for=row.scheduled_for,
                title=row.title,
                detail=row.detail,
                source=row.source.value,
                source_url=row.source_url,
            )
            for row in rows
        ],
        total=total,
        caveat=AGENDA_CAVEAT,
    )


# --- chart evidence ---------------------------------------------------------


@router.get("/assets/{ticker}/evidence", response_model=dict)
def recommendation_evidence(
    ticker: str,
    timeframe: Timeframe = Query(default=Timeframe.D1),
    bars: int = Query(default=180, ge=30, le=600),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict[str, Any]:
    """Price bars plus the levels and factors the stored recommendation named.

    One payload rather than two requests, so the chart and the prose beside it
    cannot end up describing different analyses.
    """
    evidence = for_recommendation(session, ticker, timeframe=timeframe, bars=bars)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No stored recommendation for {ticker.upper()}. Run an analysis "
                "first - the chart marks what an analysis said, and draws nothing "
                "on its own."
            ),
        )
    return evidence.as_dict()


# --- sharing ----------------------------------------------------------------


class ShareRequest(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=320)
    kind: Literal["watchlist", "analysis"]
    subject_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class ShareResponse(BaseModel):
    id: uuid.UUID
    kind: str
    subject_id: uuid.UUID
    note: str | None
    counterpart_email: str
    label: str
    created_at: str | None
    revoked_at: str | None


def _share_payload(view: sharing.ShareView) -> ShareResponse:
    payload = view.as_payload()
    return ShareResponse(
        id=uuid.UUID(payload["id"]),
        kind=payload["kind"],
        subject_id=uuid.UUID(payload["subject_id"]),
        note=payload["note"],
        counterpart_email=payload["counterpart_email"],
        label=payload["label"],
        created_at=payload["created_at"],
        revoked_at=payload["revoked_at"],
    )


@router.post("/shares", response_model=ShareResponse, status_code=status.HTTP_201_CREATED)
def create_share(
    payload: ShareRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> ShareResponse:
    """Show a watchlist or an analysis to one named account.

    Named accounts only - there is no link form of this, deliberately. A URL
    carrying investment analysis about a named company forwards itself and
    cannot be withdrawn once it is in a group chat, and the audience has to
    stay knowable for the redistribution question in §24 to have an answer.
    """
    try:
        row = sharing.share(
            session,
            owner_id=user.id,
            recipient_email=payload.recipient_email,
            kind=ShareKind(payload.kind),
            subject_id=payload.subject_id,
            note=payload.note,
        )
    except sharing.ShareRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return _share_payload(sharing._view(session, row, row.recipient_id))


@router.get("/shares/outgoing", response_model=list[ShareResponse])
def list_outgoing(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[ShareResponse]:
    """What this account has shared, including what it has withdrawn."""
    return [_share_payload(view) for view in sharing.outgoing(session, user.id)]


@router.get("/shares/incoming", response_model=list[ShareResponse])
def list_incoming(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[ShareResponse]:
    """What others are currently showing this account."""
    return [_share_payload(view) for view in sharing.incoming(session, user.id)]


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(
    share_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> None:
    if not sharing.revoke(session, owner_id=user.id, share_id=share_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active share of yours with that id.",
        )


@router.get("/shares/analysis/{result_id}", response_model=dict)
def read_shared_analysis(
    result_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict[str, Any]:
    """Read an analysis someone shared, with the recipient's caveat attached.

    A different caveat from the one its owner sees, and that is the point: the
    recipient did not choose the issuer, did not set the horizon it was framed
    for, and may not know what this platform is.
    """
    if not sharing.readable(
        session, recipient_id=user.id, kind=ShareKind.ANALYSIS, subject_id=result_id
    ):
        # 404 rather than 403 for a live analysis nobody shared: distinguishing
        # them tells a caller which analysis ids exist.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not shared with you."
        )

    result = session.get(AnalysisResult, result_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That analysis no longer exists."
        )
    asset = session.get(Asset, result.asset_id)
    return {
        "id": str(result.id),
        "ticker": asset.ticker if asset else None,
        "generated_at": result.generated_at.isoformat(),
        "analysis": (result.context_snapshot or {}).get("result"),
        "caveat": sharing.RECIPIENT_CAVEAT,
        "read_only": True,
    }
