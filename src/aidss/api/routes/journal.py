"""Investment journal, conversation, and audit log endpoints (Section 10).

The journal is FR-10 and the Reflection Agent's only input. What makes it work
is that it records what the investor *decided*, not what the platform
recommended - Section 5.2 is explicit that reflection is about the person's
decision-making, and a journal that only stored agreement with the platform
would have nothing to reflect on.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.base import AgentRunner
from aidss.agents.conversation import (
    ChatMode,
    ConversationContextBuilder,
    KnowledgeAgent,
    LearningAssistant,
    ReflectionAgent,
    ReflectionContextBuilder,
    ResearchAgent,
    journal_summary,
)
from aidss.api.deps import CommitBeforeResponse, get_db, require_permission
from aidss.api.pagination import paginate
from aidss.api.schemas import (
    AuditLogResponse,
    ChatRequest,
    ChatResponse,
    JournalEntryCreate,
    JournalEntryResponse,
    JournalSummaryResponse,
    Page,
    ReflectionResponse,
)
from aidss.collectors.normalization import normalize_ticker
from aidss.config import get_settings
from aidss.db.models import (
    ActorType,
    AnalysisResult,
    Asset,
    AuditLog,
    InvestmentJournalEntry,
    Recommendation,
    User,
)
from aidss.llm.errors import GatewayError
from aidss.llm.provisioning import build_gateway
from aidss.prompts.validator import ValidationFailure
from aidss.rag.provisioning import build_rag
from aidss.security.rbac import Permission

router = APIRouter(tags=["journal"], route_class=CommitBeforeResponse)

CHAT_DISCLAIMER = (
    "AI-generated explanation for informational purposes only. It is not investment "
    "advice from a licensed adviser, and the platform cannot place an order."
)

REFLECTION_DISCLAIMER = (
    "A reflection on your own recorded decisions, not an assessment of your returns "
    "and not a judgement about whether any decision was right. It is AI-generated "
    "from what you wrote, and it is not investment advice."
)


def _runner(session: Session) -> AgentRunner:
    try:
        return AgentRunner(build_gateway(session))
    except GatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI layer is not available: {exc}",
        ) from exc


# --- Investment journal (FR-10) --------------------------------------------


def _to_response(session: Session, entry: InvestmentJournalEntry) -> JournalEntryResponse:
    asset = session.get(Asset, entry.asset_id) if entry.asset_id else None
    return JournalEntryResponse(
        id=entry.id,
        ticker=asset.ticker if asset else None,
        decision=entry.decision,
        note=entry.note,
        recommendation_ref=entry.recommendation_ref,
        created_at=entry.created_at,
    )


@router.post("/journal", response_model=JournalEntryResponse, status_code=status.HTTP_201_CREATED)
def create_journal_entry(
    payload: JournalEntryCreate,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> JournalEntryResponse:
    """Record a decision the investor made.

    `decision` is free text on purpose. A closed vocabulary would push people
    toward the words the platform offers, and the point of the journal is what
    they actually thought - including "waited because I was not sure".
    """
    asset: Asset | None = None
    if payload.ticker:
        ticker = normalize_ticker(payload.ticker)
        asset = session.scalar(select(Asset).where(Asset.ticker == ticker))
        if asset is None:
            asset = Asset(ticker=ticker, exchange=payload.exchange)
            session.add(asset)
            session.flush()

    if payload.recommendation_ref is not None:
        recommendation = session.get(Recommendation, payload.recommendation_ref)
        if recommendation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The referenced recommendation does not exist",
            )

    entry = InvestmentJournalEntry(
        user_id=user.id,
        asset_id=asset.id if asset else None,
        decision=payload.decision,
        note=payload.note,
        recommendation_ref=payload.recommendation_ref,
    )
    session.add(entry)
    session.flush()
    return _to_response(session, entry)


@router.get("/journal", response_model=list[JournalEntryResponse])
def list_journal_entries(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> list[JournalEntryResponse]:
    entries = session.scalars(
        select(InvestmentJournalEntry)
        .where(InvestmentJournalEntry.user_id == user.id)
        .order_by(InvestmentJournalEntry.created_at.desc())
        .limit(limit)
    ).all()
    return [_to_response(session, entry) for entry in entries]


@router.get("/journal/summary", response_model=JournalSummaryResponse)
def journal_counts(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> JournalSummaryResponse:
    """Counts a UI can show without calling a model."""
    entries = session.scalars(
        select(InvestmentJournalEntry).where(InvestmentJournalEntry.user_id == user.id)
    ).all()
    return JournalSummaryResponse(**journal_summary(list(entries)))


@router.delete("/journal/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_journal_entry(
    entry_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> None:
    entry = session.scalar(
        select(InvestmentJournalEntry).where(
            InvestmentJournalEntry.id == entry_id,
            InvestmentJournalEntry.user_id == user.id,
        )
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    session.delete(entry)


@router.post("/journal/reflection", response_model=ReflectionResponse)
def reflect_on_journal(
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.MANAGE_OWN_DATA)),
) -> ReflectionResponse:
    """Surface patterns in how this investor decides (Section 5.2)."""
    context = ReflectionContextBuilder(session).build(user.id)
    agent = ReflectionAgent()

    if not agent.is_applicable(context):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=agent.skip_reason(context)
        )

    try:
        run = _runner(session).run(agent, context)
    except ValidationFailure as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The reflection could not be produced: {exc}",
        ) from exc

    output = run.output
    return ReflectionResponse(
        summary=output.summary,
        patterns=list(output.patterns),
        insufficient_evidence_for=list(output.insufficient_evidence_for),
        questions_to_consider=list(output.questions_to_consider),
        entries_reviewed=len(context.entries),
        model=run.usage.model,
        prompt_version=run.template_version,
        disclaimer=REFLECTION_DISCLAIMER,
        language=get_settings().analysis_language,
    )


# --- Conversation (Section 10 `/chat`) -------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.READ_ANALYSIS)),
) -> ChatResponse:
    """Free-form question answering, grounded in retrieved context.

    The mode is supplied rather than inferred. Guessing intent from the text
    would add a classifier that can be wrong, needs its own evaluation, and
    would quietly route a research question to an explainer.
    """
    rag = build_rag(session)
    context = ConversationContextBuilder(session, rag).build(
        payload.question, mode=payload.mode, user_id=user.id, ticker=payload.ticker
    )

    agent = {
        ChatMode.LEARN: LearningAssistant,
        ChatMode.RESEARCH: ResearchAgent,
        ChatMode.KNOWLEDGE: KnowledgeAgent,
    }[payload.mode]()

    if not agent.is_applicable(context):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=agent.skip_reason(context)
        )

    try:
        run = _runner(session).run(agent, context)
    except ValidationFailure as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The answer could not be produced: {exc}",
        ) from exc

    output = run.output
    return ChatResponse(
        mode=payload.mode,
        agent=run.agent,
        answer=output.answer,
        summary=output.summary,
        data_sufficiency=output.data_sufficiency.value,
        sources_used=list(output.sources_used),
        # The passages themselves, so an answer can be checked against what it
        # was given rather than taken on trust.
        retrieved=context.sources_payload(),
        follow_up_questions=list(output.follow_up_questions),
        model=run.usage.model,
        prompt_version=run.template_version,
        disclaimer=CHAT_DISCLAIMER,
    )


# --- Audit log (Sections 10, 13) -------------------------------------------


@router.get("/audit-logs", response_model=Page[AuditLogResponse])
def export_audit_logs(
    entity: str | None = Query(default=None),
    actor_type: ActorType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_AUDIT_LOG)),
) -> Page[AuditLogResponse]:
    """Export the append-only audit trail (Section 13).

    Read-only, and there is no endpoint that writes or deletes one. An audit
    log an application can edit is not an audit log.
    """
    stmt = select(AuditLog)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)

    rows, total = paginate(session, stmt, AuditLog.created_at.desc(), limit, offset)
    return Page(
        items=[
            AuditLogResponse(
                id=row.id,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                action=row.action,
                entity=row.entity,
                entity_id=row.entity_id,
                before=row.before,
                after=row.after,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-logs/analysis/{analysis_result_id}", response_model=dict)
def reproduce_analysis(
    analysis_result_id: uuid.UUID,
    session: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.READ_AUDIT_LOG)),
) -> dict:
    """Everything needed to explain one stored analysis (Section 1).

    The context the agents saw, the prompt versions, the models, and the output
    - which together are what "full traceability" has to mean in practice.
    """
    result = session.get(AnalysisResult, analysis_result_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    asset = session.get(Asset, result.asset_id)
    return {
        "analysis_result_id": str(result.id),
        "ticker": asset.ticker if asset else None,
        "generated_at": result.generated_at.isoformat(),
        "model_used": result.model_used,
        "prompt_version": result.prompt_version,
        "context_and_output": result.context_snapshot,
    }
