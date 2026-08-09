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
from aidss.agents.risk_profile import QUESTIONS, IncompleteAnswers, derive
from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.collab import sharing
from aidss.db.models import (
    AlertKind,
    AnalysisResult,
    Asset,
    SavedScreen,
    ShareKind,
    User,
    Watchlist,
    WatchlistItem,
)
from aidss.domain.types import Timeframe
from aidss.monitoring.agenda import upcoming
from aidss.recommendations.evidence import for_recommendation
from aidss.screener.custom import (
    SCREEN_CAVEAT,
    InvalidRule,
    Rule,
    describe_fields,
    parse,
)
from aidss.screener.custom import run as run_screen
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


# --- risk screening ---------------------------------------------------------


class RiskAnswers(BaseModel):
    #: Question key to chosen option key. Validated against the instrument
    #: rather than typed here: the questions are data, and duplicating their
    #: shape in a schema means adding a question in two places.
    answers: dict[str, str]


class RiskProfileResponse(BaseModel):
    risk_appetite: RiskAppetite
    investment_horizon: Horizon
    tolerance_score: int
    capacity_score: int
    limited_by: str
    answers: dict[str, str]
    caveat: str


RISK_CAVEAT = (
    "This shapes how analysis is written for you - what gets emphasised and how "
    "fully the downside is spelled out. It never changes what an analysis "
    "concludes: the stance, the levels and the confidence are properties of the "
    "evidence, not of who is reading. It is not a suitability assessment and not "
    "advice about what you should hold."
)


@router.get("/me/risk-profile/questions", response_model=dict)
def risk_questions() -> dict[str, Any]:
    """The instrument, as data.

    Option *keys* only - the wording lives in the interface's message table, so
    a question can be reworded in either language without touching the scoring
    that produced somebody's stored profile.
    """
    return {
        "questions": [
            {
                "key": question.key,
                "dimension": question.dimension.value,
                "options": [option.key for option in question.options],
            }
            for question in QUESTIONS
        ],
        "caveat": RISK_CAVEAT,
    }


@router.post("/me/risk-profile", response_model=RiskProfileResponse)
def submit_risk_profile(
    payload: RiskAnswers,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> RiskProfileResponse:
    """Score the answers, store them, and set the profile they imply.

    The answers are stored as well as the result. A derivation nobody can
    inspect is a label the reader has to take on faith, and one that cannot be
    re-run is frozen the day the scoring changes.

    The derived appetite and horizon are written with ``source="derived"``. The
    Memory Manager keeps a stated preference above an inferred one, so somebody
    who has already set their appetite by hand is not overruled by a
    questionnaire - and somebody who takes the questionnaire and then disagrees
    can still override it on the profile screen.
    """
    try:
        profile = derive(payload.answers)
    except IncompleteAnswers as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    manager = MemoryManager(session)
    manager.remember(user.id, PreferenceKey.RISK_ANSWERS, profile.answers, source="stated")
    manager.remember(
        user.id, PreferenceKey.RISK_APPETITE, profile.risk_appetite, source="derived"
    )
    manager.remember(
        user.id, PreferenceKey.HORIZON, profile.investment_horizon, source="derived"
    )

    return RiskProfileResponse(**profile.as_payload(), caveat=RISK_CAVEAT)


@router.get("/me/risk-profile", response_model=RiskProfileResponse | None)
def read_risk_profile(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> RiskProfileResponse | None:
    """The stored screening, re-scored on read.

    Re-derived rather than returning a stored label: the scoring is the part
    most likely to change, and a profile that keeps reporting last month's
    thresholds is worse than one that says it needs retaking.
    """
    memory = MemoryManager(session).load(user.id)
    answers = memory.preferences.get(PreferenceKey.RISK_ANSWERS)
    if not isinstance(answers, dict) or not answers:
        return None
    try:
        profile = derive({str(k): str(v) for k, v in answers.items()})
    except IncompleteAnswers:
        # Stored against an older version of the instrument. Reported as "not
        # taken" rather than as an error: the reader's next action is the same
        # either way, and it is retaking it.
        return None
    return RiskProfileResponse(**profile.as_payload(), caveat=RISK_CAVEAT)


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
    stay knowable for the redistribution question in Section 26 to have an answer.
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


# --- custom screens ---------------------------------------------------------


class RuleRequest(BaseModel):
    field: str = Field(max_length=80)
    operator: str = Field(max_length=20)
    #: Deliberately untyped here. A number, a pair, a boolean, a date, or a
    #: list of criteria depending on the field - and the builder validates it
    #: against the field's declared type, which is the only place that knows.
    value: Any = None


class ScreenRequest(BaseModel):
    rules: list[RuleRequest] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=100, ge=1, le=500)


class SaveScreenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    rules: list[RuleRequest] = Field(default_factory=list, max_length=20)


class SavedScreenResponse(BaseModel):
    id: uuid.UUID
    name: str
    rules: list[dict[str, Any]]


@router.get("/screens/fields", response_model=dict)
def screen_fields(
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict[str, Any]:
    """The vocabulary a screen may use: fields, their types, their operators.

    Served rather than hardcoded in the interface, for the same reason the
    sub-sector filter reads its options from the data: a second copy goes stale
    the first time a signal is added, and the failure is a field that exists
    and cannot be filtered on.
    """
    return {
        "fields": describe_fields(),
        "criteria": [kind.value for kind in AlertKind],
        "caveat": SCREEN_CAVEAT,
    }


def _parsed(rules: list[RuleRequest]) -> list[Rule]:
    try:
        return parse([rule.model_dump() for rule in rules])
    except InvalidRule as exc:
        # 422 with the builder's own sentence. A rule is written by a person,
        # so the reason it was refused has to be readable by one.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/screens/preview", response_model=dict)
def preview_screen(
    payload: ScreenRequest,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict[str, Any]:
    """Run a screen without saving it.

    The response reports `considered` beside `matched` on purpose: a filter
    that keeps most of the exchange is not filtering, and the denominator is
    the only thing that shows it.
    """
    return run_screen(session, _parsed(payload.rules), limit=payload.limit).as_payload()


@router.get("/screens", response_model=list[SavedScreenResponse])
def list_screens(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> list[SavedScreenResponse]:
    rows = session.scalars(
        select(SavedScreen)
        .where(SavedScreen.user_id == user.id)
        .order_by(SavedScreen.name)
    ).all()
    return [
        SavedScreenResponse(id=row.id, name=row.name, rules=list(row.rules or []))
        for row in rows
    ]


@router.post("/screens", response_model=SavedScreenResponse, status_code=status.HTTP_201_CREATED)
def save_screen(
    payload: SaveScreenRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> SavedScreenResponse:
    """Store a screen, validating it first.

    Validated before it is written rather than when it is next run: a screen
    that saves cleanly and fails every time afterwards is worse than one that
    refuses to save.
    """
    rules = _parsed(payload.rules)
    name = payload.name.strip()

    existing = session.scalar(
        select(SavedScreen).where(
            SavedScreen.user_id == user.id, SavedScreen.name == name
        )
    )
    if existing is None:
        existing = SavedScreen(user_id=user.id, name=name)
        session.add(existing)
    existing.rules = [rule.as_payload() for rule in rules]
    session.flush()
    return SavedScreenResponse(id=existing.id, name=existing.name, rules=list(existing.rules))


@router.post("/screens/{screen_id}/run", response_model=dict)
def run_saved_screen(
    screen_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> dict[str, Any]:
    """Run a stored screen, re-validating its rules on the way.

    Re-validated because the vocabulary can change under a saved screen. A rule
    naming a signal that no longer exists then produces a sentence saying so,
    rather than a database error about a column nobody wrote.
    """
    row = session.scalar(
        select(SavedScreen).where(
            SavedScreen.id == screen_id, SavedScreen.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No screen of yours with that id."
        )

    try:
        rules = parse(list(row.rules or []))
    except InvalidRule as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{row.name!r} can no longer run: {exc}",
        ) from exc

    return run_screen(session, rules, limit=limit).as_payload()


@router.delete("/screens/{screen_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_screen(
    screen_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> None:
    row = session.scalar(
        select(SavedScreen).where(
            SavedScreen.id == screen_id, SavedScreen.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No screen of yours with that id."
        )
    session.delete(row)
