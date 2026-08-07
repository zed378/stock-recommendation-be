"""API request and response schemas (Section 10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from aidss.agents.conversation import ChatMode
from aidss.db.models.news import ScheduleStatus
from aidss.db.models.system import ActorType, JobStatus
from aidss.db.models.user import HoldingInputMethod, UserRole
from aidss.domain.types import InvestmentHorizon, RecommendationLabel, Timeframe
from aidss.prompts.language import OutputLanguage


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth -----------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserResponse(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    mfa_enabled: bool


# --- Assets & market data --------------------------------------------------


class AssetCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    exchange: str = "IDX"
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str = "IDR"


class AssetResponse(ORMModel):
    id: uuid.UUID
    ticker: str
    exchange: str
    name: str | None
    sector: str | None
    industry: str | None
    currency: str


class CandleResponse(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class IngestRequest(BaseModel):
    timeframe: Timeframe = Timeframe.D1
    days: int = Field(default=365, ge=1, le=3650)


class IngestResponse(BaseModel):
    ticker: str
    timeframe: Timeframe
    provider: str
    fetched: int
    inserted: int
    updated: int
    rejected: int
    rejection_reasons: list[str]
    indicators_inserted: int
    indicators_updated: int


class FundamentalIngestResponse(BaseModel):
    ticker: str
    fetched: int
    inserted: int
    updated: int
    #: True when the provider publishes no fundamental data at all - a fact,
    #: not a failure.
    unsupported: bool
    note: str


class FundamentalMetricResponse(BaseModel):
    metric: str
    period: date
    #: quarterly / annual / ttm. Travels with the number, because a quarterly
    #: figure read as annual is a factor-of-four error.
    period_type: str
    value: Decimal | None
    source: str


# --- Indicators & features -------------------------------------------------


class IndicatorSnapshotResponse(BaseModel):
    ticker: str
    timeframe: Timeframe
    snapshot: dict[str, Any]
    features: dict[str, Any]
    #: Attached to every analytical response, per Section 2.7.
    disclaimer: str


# --- AI analysis (Phase 4) -------------------------------------------------


class AnalysisRequest(BaseModel):
    timeframe: Timeframe = Timeframe.D1
    exchange: str = "IDX"
    #: Off skips the Recommendation Agent, which is the most expensive call in
    #: the run. Useful when only the analyzer readings are wanted.
    include_recommendation: bool = True


class RecommendationResponse(BaseModel):
    """The complete Section 5.4 structure.

    Prices are strings so a Decimal survives JSON without being rounded
    through a float on the way out.
    """

    label: RecommendationLabel
    #: The calibrated score. Section 5.4 requires a consistent calibration
    #: rather than an arbitrary number from the model.
    confidence: float = Field(ge=0, le=100)
    #: How that score was reached, so it can be explained rather than trusted.
    confidence_basis: dict[str, Any]
    #: Kept for comparison against the calibrated figure; never published as
    #: the confidence itself.
    model_self_reported_confidence: float | None = None

    reasoning: str
    supporting_factors: list[str]
    #: Never empty - enforced before the recommendation is stored.
    conflicting_factors: list[str]
    risk_factors: list[str]
    bullish_scenario: str
    bearish_scenario: str

    support_level: str | None = None
    resistance_level: str | None = None
    target_price: str | None = None
    target_price_method: str | None = None
    #: Named a suggestion throughout, in the schema as well as the prose.
    suggested_stop: str | None = None
    suggested_stop_method: str | None = None

    horizon: InvestmentHorizon
    prompt_version: str | None = None
    model: str | None = None
    provider: str | None = None
    attempts: int | None = None

    #: Which language the prose fields above are in - the text that passed
    #: schema validation and the execution-language guard.
    language: str = "id"
    #: Renderings of that prose, keyed by language, produced during the same
    #: run as the analysis. Present means the reader can switch language with
    #: no request at all. Absent means the on-demand `/translate` endpoint is
    #: the fallback - a slower path, not a missing feature.
    translations: dict[str, Any] = Field(default_factory=dict)


class AgentSkipResponse(BaseModel):
    agent: str
    reason: str


class AnalysisUsageResponse(BaseModel):
    total_tokens: int
    estimated_cost: str


class AnalysisResponse(BaseModel):
    ticker: str
    timeframe: Timeframe
    analysis_result_id: uuid.UUID | None
    #: Absent when it was not requested, or when the Section 5.4 rules rejected
    #: every attempt - in which case the reason appears under `failed`.
    recommendation: RecommendationResponse | None = None
    #: Keyed by agent name; each value is that agent's validated output plus
    #: the provider, model, and prompt version that produced it.
    agents: dict[str, Any]
    #: Agents that had nothing to work with, kept distinct from failures so a
    #: missing data source does not read as a broken component.
    skipped: list[AgentSkipResponse]
    failed: list[AgentSkipResponse]
    usage: AnalysisUsageResponse
    disclaimer: str


# --- Watchlist -------------------------------------------------------------


#: The group an item belongs to. Named watchlists were always in the schema -
#: `watchlists` carries a `name` with a unique constraint per user - but every
#: endpoint hardcoded "Default", so the grouping existed and was unreachable.
#: `category` is that name, surfaced.
DEFAULT_CATEGORY = "Default"


class WatchlistItemCreate(BaseModel):
    ticker: str
    exchange: str = "IDX"
    note: str | None = None
    #: Created on first use rather than declared up front: a category with no
    #: members is not a thing anyone wants to manage.
    category: str = Field(default=DEFAULT_CATEGORY, min_length=1, max_length=120)


class WatchlistItemResponse(BaseModel):
    id: uuid.UUID
    ticker: str
    exchange: str
    note: str | None
    added_at: datetime
    category: str = DEFAULT_CATEGORY
    #: Carried so the list is readable and searchable by more than a code.
    #: `name` is null until an ingest fills it in, which the UI has to handle.
    name: str | None = None
    sector: str | None = None


class WatchlistCategoryResponse(BaseModel):
    name: str
    count: int


class WatchlistItemMove(BaseModel):
    category: str = Field(min_length=1, max_length=120)


class WatchlistCategoryRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WatchlistCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# --- Administration (users and news sources) -------------------------------


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    status: str
    #: What the status *does* right now. A suspension whose deadline has passed
    #: is still recorded as suspended, and showing only the stored value would
    #: have an admin chasing a lock that no longer exists.
    effective_status: str
    suspended_until: datetime | None
    status_reason: str | None
    status_changed_at: datetime | None
    created_at: datetime


class RoleChangeRequest(BaseModel):
    role: UserRole


class SuspendRequest(BaseModel):
    #: Null means indefinite - still a suspension rather than a ban, because
    #: the two mean different things to the person on the other end.
    until: datetime | None = None
    reason: str | None = Field(default=None, max_length=1000)


class BanRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class NewsSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    #: May contain ``{ticker}``, in which case it is substituted per asset and
    #: the publisher does the searching.
    feed_url: str = Field(min_length=8, max_length=1000)
    #: Restrict to one issuer. Null means the feed is read for every asset.
    ticker: str | None = None
    is_active: bool = True


class NewsSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    feed_url: str | None = Field(default=None, min_length=8, max_length=1000)
    is_active: bool | None = None
    #: Null is ambiguous here - it means both "leave it alone" and "unbind this
    #: from its issuer". The route distinguishes them with `model_fields_set`,
    #: so sending `{"ticker": null}` unbinds and omitting the key does not.
    ticker: str | None = None


class NewsSourceResponse(BaseModel):
    id: uuid.UUID
    name: str
    feed_url: str
    ticker: str | None
    is_active: bool
    is_templated: bool
    last_fetched_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_entry_count: int
    consecutive_failures: int
    created_at: datetime


class NewsSourceTestResponse(BaseModel):
    """What a feed actually returned, right now.

    Exists because the alternative was adding a source, waiting for a schedule,
    and inferring from an empty list whether the URL was wrong, the feed was
    empty, or nothing mentioned the ticker.
    """

    ok: bool
    entries: int
    error: str | None = None
    #: The newest few headlines, so the admin can see it is the right feed
    #: rather than only that something parsed.
    sample: list[str] = Field(default_factory=list)
    newest_published_at: datetime | None = None


# --- Screening, strategy, monitoring ---------------------------------------


class StockPickResponse(BaseModel):
    horizon: str
    generated_at: datetime
    considered: int
    insufficient_history: list[str]
    picks: list[dict[str, Any]]
    #: Repeated on the response rather than left to the interface. A ranked
    #: list of tickers reads as a forecast unless it says otherwise on the same
    #: screen, and an API client has no interface at all.
    caveat: str


class GuidanceResponse(BaseModel):
    position: str
    stance: str
    rationale: str
    conditions: list[str]
    invalidated_if: list[str]
    reference_levels: dict[str, str]


class StrategyResponse(BaseModel):
    ticker: str
    label: str
    confidence: float
    as_of: datetime
    #: Both readings, always. Returning only the caller's own side would hide
    #: that an asset can be worth keeping and not worth buying at the same time.
    not_holding: GuidanceResponse
    holding: GuidanceResponse
    disclaimer: str
    #: The same two readings in every other language, keyed by language code.
    #: Not a machine rendering: this text is product copy with a price
    #: interpolated into it, so both languages are written by hand and neither
    #: is the original. Sent with the response because it costs nothing to
    #: build and switching should not be a request.
    translations: dict[str, Any] = Field(default_factory=dict)


class QuoteSnapshotResponse(BaseModel):
    ticker: str
    exchange: str
    price: Decimal | None
    previous_close: Decimal | None
    quoted_at: datetime | None
    observed_at: datetime | None
    source: str | None
    #: The free sources are delayed by roughly fifteen minutes. Shown rather
    #: than implied, because an interface presenting a delayed price as current
    #: invites decisions on numbers that have already moved.
    is_delayed: bool


class TranslationRequest(BaseModel):
    """Prose to render in the other language.

    The caller sends the fields it wants translated rather than an analysis id,
    so the same endpoint serves an analysis, a reflection, and a chat answer
    without three near-identical routes. Non-prose keys are filtered server
    side: translating a stance label would produce a value the enum does not
    contain.
    """

    fields: dict[str, Any]
    language: OutputLanguage
    #: Journal reflections are personal financial data and must route through
    #: the sensitive path, which refuses a third-party provider.
    is_personal: bool = False


class AlertResponse(BaseModel):
    id: uuid.UUID
    ticker: str
    kind: str
    direction: str
    message: str
    observed_price: Decimal | None
    reference_price: Decimal | None
    #: Where a stance travels, as data. Never as an instruction in the message.
    context: dict[str, Any] | None
    triggered_at: datetime
    acknowledged_at: datetime | None


# --- Portfolio -------------------------------------------------------------


class HoldingUpsert(BaseModel):
    ticker: str
    exchange: str = "IDX"
    quantity: Decimal = Field(gt=0)
    average_price: Decimal = Field(gt=0)
    input_method: HoldingInputMethod = HoldingInputMethod.MANUAL


class HoldingResponse(BaseModel):
    id: uuid.UUID
    ticker: str
    exchange: str
    quantity: Decimal
    average_price: Decimal
    input_method: HoldingInputMethod
    updated_at: datetime


class PortfolioResponse(BaseModel):
    id: uuid.UUID
    name: str
    base_currency: str
    holdings: list[HoldingResponse]


# --- Portfolio intelligence (Phase 6) --------------------------------------


class PortfolioAnalysisResponse(BaseModel):
    portfolio: str
    #: Deterministic figures - concentration, weights, diversification.
    metrics: dict[str, Any]
    #: Historical risk figures, each carrying its observation count.
    risk: dict[str, Any]
    correlation: dict[str, Any]
    holdings: list[dict[str, Any]]
    #: Model narrative, keyed by agent, with the prompt version that produced it.
    agents: dict[str, Any]
    skipped: list[AgentSkipResponse]
    failed: list[AgentSkipResponse]
    disclaimer: str


class AllocationChangeRequest(BaseModel):
    ticker: str
    #: Absolute target quantity, not a delta. Zero removes the position.
    quantity: Decimal = Field(ge=0)


class SimulationRequest(BaseModel):
    changes: list[AllocationChangeRequest] = Field(min_length=1, max_length=50)


class SimulationResponse(BaseModel):
    changes: list[dict[str, Any]]
    before: dict[str, Any]
    after: dict[str, Any]
    #: What actually moved, so a reader need not diff two payloads by eye.
    deltas: dict[str, Any]
    correlation_after: dict[str, Any]
    note: str
    disclaimer: str


# --- Investment journal (FR-10) --------------------------------------------


class JournalEntryCreate(BaseModel):
    #: Free text on purpose: a closed vocabulary would push people toward the
    #: words the platform offers, and the point is what they actually thought.
    decision: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=4000)
    ticker: str | None = None
    exchange: str = "IDX"
    #: Optional link to a recommendation. Nullable because an investor does not
    #: always follow, or even consult, one.
    recommendation_ref: uuid.UUID | None = None


class JournalEntryResponse(BaseModel):
    id: uuid.UUID
    ticker: str | None
    decision: str
    note: str | None
    recommendation_ref: uuid.UUID | None
    created_at: datetime


class JournalSummaryResponse(BaseModel):
    entries: int
    by_decision: dict[str, int]
    first_entry_at: str | None
    linked_to_recommendation: int


class ReflectionResponse(BaseModel):
    summary: str
    #: Patterns in how this investor decides - not an assessment of returns.
    patterns: list[str]
    #: Where the journal is too thin to support a pattern. Naming it is what
    #: stops the agent inventing one.
    insufficient_evidence_for: list[str]
    questions_to_consider: list[str]
    entries_reviewed: int
    model: str | None
    prompt_version: str | None
    disclaimer: str
    #: Which language the prose above is in. Stated rather than left for the
    #: client to infer from its own locale: the output language is a server
    #: setting, so a reader with the interface in English is still looking at
    #: Indonesian prose on a default deployment - and a switch that guessed
    #: would offer to translate it into the language it is already in.
    language: str = "id"


# --- Conversation (Section 10 `/chat`) -------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    #: Supplied, not inferred: guessing intent would add a classifier that can
    #: be wrong and would need its own evaluation.
    mode: ChatMode = ChatMode.KNOWLEDGE
    #: Required by research mode, ignored by the others.
    ticker: str | None = None


class ChatResponse(BaseModel):
    mode: ChatMode
    agent: str
    answer: str
    summary: str
    data_sufficiency: str
    #: What the model says it drew on. Empty means it answered from its own
    #: training rather than from retrieved context.
    sources_used: list[str]
    #: The passages themselves, so the answer can be checked against what it
    #: was given.
    retrieved: list[dict[str, Any]]
    follow_up_questions: list[str]
    model: str | None
    prompt_version: str | None
    disclaimer: str


# --- Audit log (Sections 10, 13) -------------------------------------------


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_type: ActorType
    actor_id: str | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


# --- Knowledge base & RAG (Phase 7) ----------------------------------------


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    source: str | None = None
    category: str | None = None


class KnowledgeDocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    source: str | None
    category: str | None
    #: How many retrievable chunks the document produced. Zero means it was
    #: stored but is unreachable by search.
    chunks: int
    uploaded_at: datetime


class RetrievalResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]


# --- Scheduled news ingestion (Section 6.3) --------------------------------


class CronPresetResponse(BaseModel):
    key: str
    label: str
    expression: str
    suited_to: str


class NewsScheduleCreate(BaseModel):
    ticker: str
    exchange: str = "IDX"
    #: Either a preset key or a custom expression; the preset wins if both are
    #: supplied, because it is the one the user actually clicked.
    preset: str | None = None
    cron_expression: str | None = None


class NewsScheduleResponse(BaseModel):
    id: uuid.UUID
    ticker: str
    cron_expression: str
    preset_label: str | None
    is_active: bool
    #: `needs_attention` after repeated failures - flagged rather than
    #: disabled, so a broken schedule cannot be mistaken for a quiet one.
    status: ScheduleStatus
    consecutive_failures: int
    last_fetched_at: datetime | None
    next_run_at: datetime | None


class ScheduleRunResponse(BaseModel):
    ticker: str
    fetched: int
    inserted: int
    duplicates: int
    scored: int
    chunks_indexed: int
    error: str | None
    #: Non-fatal problems. Articles were stored, but something downstream did
    #: not complete - kept separate so a sentiment outage does not read as a
    #: failed ingestion.
    warnings: list[str]
    status: ScheduleStatus
    next_run_at: datetime | None


# --- Background jobs (Sections 2.6, 4) -------------------------------------


class JobAcceptedResponse(BaseModel):
    job_id: uuid.UUID
    job_type: str
    #: True when an identical job was already queued and this returns that one.
    deduplicated: bool
    poll_url: str
    note: str


class JobResponse(BaseModel):
    id: uuid.UUID
    job_type: str
    #: `dead` means the retries are exhausted; `last_error` says why.
    status: JobStatus
    retry_count: int
    max_retries: int
    last_error: str | None
    result: dict[str, Any] | None
    available_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class QueueStatsResponse(BaseModel):
    by_status: dict[str, int]
    #: What this build knows how to run. A job type missing from here will
    #: dead-letter.
    registered_job_types: list[str]
    #: Which process currently holds the scheduler lease, and whether it is
    #: still live. Absent or `expired` means nothing is enqueueing scheduled
    #: work - a failure that otherwise looks exactly like "nothing is due".
    scheduler_leader: dict[str, str] | None = None
    note: str


# --- Reporting, notifications, admin (Phase 8) -----------------------------


class ReportResponse(BaseModel):
    title: str
    generated_at: datetime
    #: The document itself. Request `?format=markdown` to get it as the
    #: response body rather than a string inside JSON.
    markdown: str
    #: The same content as data, for a UI that lays it out itself.
    payload: dict[str, Any]


class NotificationResponse(BaseModel):
    id: uuid.UUID
    channel: str
    subject: str | None
    message: str
    status: str
    created_at: datetime
    #: Which event this was, so the interface groups and routes on the
    #: vocabulary rather than by parsing the subject line back into a category.
    event: str | None = None
    #: Structured detail - ticker, counts, and the stance where one applies.
    #: The prose says what happened; anything actionable is here, rendered
    #: beside a link back to the screen that carries the full context.
    context: dict[str, Any] | None = None


class UnreadCountResponse(BaseModel):
    unread: int


class OperationsOverviewResponse(BaseModel):
    generated_at: str
    window_days: int
    inventory: dict[str, Any]
    ingestion: dict[str, Any]
    #: Token and cost totals, per agent. Estimates from the configured price
    #: table, not billed amounts (Section 12.9).
    ai_usage: dict[str, Any]
    #: Things an operator should look at: flagged schedules, recent failures.
    attention: list[dict[str, Any]]
    providers: dict[str, Any]


# --- Providers (admin) -----------------------------------------------------


class BudgetStatusResponse(BaseModel):
    spent: str
    ceiling: str | None
    #: ok / warning / exceeded. `exceeded` means further AI calls are blocked
    #: until the 24-hour window rolls forward (Section 12.9).
    state: str
    utilisation: float | None
    window_start: str
    message: str


class ProviderInventoryResponse(BaseModel):
    registered: dict[str, list[str]]
    active: dict[str, str]


class IssuerResponse(BaseModel):
    """One listed company from the IDX directory.

    The aliases are included because they are the editable part: when a story
    is tagged to the wrong company, the alias that matched is what has to
    change, and it cannot be corrected if it cannot be seen.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    name: str
    sector: str | None = None
    sub_sector: str | None = None
    listing_board: str | None = None
    website: str | None = None
    #: Only the extras somebody typed. The index entry and the names derived
    #: from the registered one are not stored here.
    aliases: list[str] = Field(default_factory=list)
    #: Everything that actually matches, index and derivation included. Without
    #: it the panel shows an empty alias list for BBCA while "BCA" is matching
    #: perfectly well, which reads as the feature being broken.
    effective_aliases: list[str] = Field(default_factory=list)
    is_listed: bool
    synced_at: datetime


class IssuerUpdateRequest(BaseModel):
    """Corrections to an issuer. Only the aliases are editable.

    Everything else comes from the exchange and would be overwritten by the
    next synchronisation, so offering it as a field would be offering an edit
    that silently expires.
    """

    aliases: list[str] = Field(
        description=(
            "Names this company is known by in the press. Matched case-insensitively "
            "on word boundaries, so keep them distinctive: a single common word will "
            "tag hundreds of unrelated stories."
        )
    )


class NewsTagResponse(BaseModel):
    """An issuer a story was attributed to, and why."""

    model_config = ConfigDict(from_attributes=True)

    ticker: str
    method: str
    matched_text: str


class AlertBatchRequest(BaseModel):
    """The alerts a batch action applies to.

    Non-empty by construction. The alternative - an empty list meaning "all" -
    puts the difference between "acknowledge these three" and "delete
    everything" in whether a client's filter happened to return anything, which
    is not a distinction to leave to a bug upstream. Acting on everything has
    its own endpoint, with the scope written in the URL.
    """

    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class AlertBatchResponse(BaseModel):
    """How many alerts the action actually changed.

    Reported rather than assumed equal to what was asked for: ids belonging to
    somebody else, or already acknowledged, are skipped, and a caller that
    selected five and changed three should be able to tell.
    """

    affected: int


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One window onto a list, with enough context to move.

    A bare list plus a `limit` is not pagination: the caller cannot tell a full
    page from the end of the data, cannot ask for the next one, and cannot show
    how much there is. Every admin list here grows without bound - audit rows,
    jobs, issuers - so "the first hundred, silently" is a screen that stops
    telling the truth on the hundred and first.

    `total` is the count before the window, not after, which is the only way a
    reader learns there is more than they can see.
    """

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PlatformSettingsResponse(BaseModel):
    """Operator choices that apply without a redeploy."""

    registration_open: bool
    news_sweep_cron: str


class PlatformSettingsUpdate(BaseModel):
    """Only the keys sent are changed; omitted keys keep their value.

    `None` rather than a default, so "leave this alone" and "set it to false"
    are different requests. A partial update that silently reset the keys it
    did not mention would close registration every time somebody changed the
    news schedule.
    """

    registration_open: bool | None = None
    news_sweep_cron: str | None = Field(default=None, max_length=120)


class AIProviderResponse(BaseModel):
    """A configured provider, without its credential.

    `api_key_hint` is what the interface shows: enough to recognise which key
    is stored, never enough to use it. The value itself is not returned by any
    endpoint - not to admins, not on the row that was just written.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    adapter_name: str
    base_url: str | None = None
    default_model: str | None = None
    role: str
    priority: int
    is_active: bool
    self_hosted: bool
    timeout_seconds: float | None = None
    api_key_hint: str | None = None
    input_cost_per_1k: Decimal | None = None
    output_cost_per_1k: Decimal | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_checked_at: datetime | None = None


class AIProviderWrite(BaseModel):
    """Creating or updating a provider.

    `api_key` is write-only and optional on update: omitting it keeps the key
    already stored, which is what an admin editing the model name expects.
    Sending an empty string clears it, which is what a switch to a local model
    needing no key expects. Those are different intents and are kept apart.
    """

    name: str = Field(min_length=1, max_length=80)
    adapter_name: str = Field(default="openai_compatible", max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=120)
    #: Which task complexities this provider may serve. "general" handles
    #: everything, which is right for a single-provider deployment.
    role: str = Field(default="general")
    priority: int = Field(default=100, ge=0, le=10_000)
    is_active: bool = True
    #: Declared by the operator when inference runs on infrastructure they
    #: control at a public domain - the platform cannot tell by looking, and
    #: the answer decides whether personal financial data may go there.
    self_hosted: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    api_key: str | None = Field(default=None, max_length=400)
    input_cost_per_1k: Decimal | None = Field(default=None, ge=0)
    output_cost_per_1k: Decimal | None = Field(default=None, ge=0)


class AIProviderUpdate(BaseModel):
    """Changing a provider. Every field optional, and that is the point.

    A shared schema with the create request would make `name` required here,
    so a caller correcting a model name would have to resend the whole row -
    and the moment they resend a partial one, the fields they left out take
    their defaults. That is how a fallback chain reorders itself because
    somebody fixed a typo.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    adapter_name: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=120)
    role: str | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None
    self_hosted: bool | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    #: Absent keeps the stored key, `""` clears it, a value replaces it.
    api_key: str | None = Field(default=None, max_length=400)
    input_cost_per_1k: Decimal | None = Field(default=None, ge=0)
    output_cost_per_1k: Decimal | None = Field(default=None, ge=0)


class AIProviderTestResponse(BaseModel):
    """What the provider answered, just now."""

    ok: bool
    latency_ms: int | None = None
    model: str | None = None
    reply: str | None = None
    error: str | None = None


class AdminUserCreate(BaseModel):
    """An account created by an administrator rather than by its owner.

    A password is required rather than generated: a generated one has to be
    transmitted somehow, and every convenient channel for that is a worse place
    for a credential than wherever the admin was going to type it anyway.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)
    role: UserRole = UserRole.INVESTOR


class MarketScanResponse(BaseModel):
    """One issuer's result from the whole-market scan.

    `signals` carries the computed values behind the match, so a reader can see
    *why* a ticker is on the list rather than only that it is.
    """

    ticker: str
    session_date: date
    close: Decimal | None = None
    matched: list[str] = Field(default_factory=list)
    matched_count: int
    signals: dict[str, Any] = Field(default_factory=dict)
