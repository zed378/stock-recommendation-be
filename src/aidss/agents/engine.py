"""Analysis Engine - multi-agent orchestration (Section 14.1).

Runs the flow of the Section 14.1 diagram as far as Phase 4 goes: build context,
run the applicable analyzers, synthesise, validate, persist.

Two behaviours are worth stating outright, because both are choices rather
than accidents:

  * **A failing analyzer does not fail the run.** If the news provider is down
    or one model returns junk twice, the remaining analyzers still produce a
    result and the failure is reported alongside it. A partial analysis that
    says what is missing beats no analysis at all.
  * **Skipped is distinct from failed.** An agent that had no data to work
    with is recorded as skipped with its reason. Collapsing the two would hide
    the difference between "there is no fundamental data" and "the fundamental
    analyzer is broken".
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.agents.analyzers import (
    FundamentalAnalyzer,
    MarketAnalyzer,
    NewsAnalyzer,
    SummaryAgent,
    TechnicalAnalyzer,
)
from aidss.agents.base import Agent, AgentRun, AgentRunner, AgentSkip, ConversationRecorder
from aidss.agents.context import AnalysisContext, ContextBuilder
from aidss.agents.triage import Triage, triage_for
from aidss.db.models import AIConversation, AnalysisResult, Asset, Recommendation
from aidss.domain.types import Timeframe
from aidss.llm.errors import GatewayError
from aidss.llm.gateway import LLMGateway
from aidss.prompts.manager import PromptComposer
from aidss.prompts.translation import translatable_fields, translate
from aidss.prompts.validator import ValidationFailure
from aidss.recommendations.engine import (
    RecommendationEngine,
    RecommendationRejected,
    RecommendationResult,
)
from aidss.recommendations.rendering import other_language, render_translation
from aidss.reporting.notifications import NotificationEvent, NotificationService

logger = logging.getLogger("aidss.analysis")


@dataclass(slots=True)
class AgentFailure:
    agent: str
    reason: str


#: Agents whose output is a synthesis of others rather than direct evidence.
#: Excluded from `analyzer_runs` so they are never fed back into themselves or
#: counted as an independent source during calibration.
_DERIVED_AGENTS = frozenset({"summary_agent", "recommendation_agent"})


@dataclass(slots=True)
class AnalysisRun:
    """Everything one analysis produced, including what did not work."""

    asset_ticker: str
    timeframe: Timeframe
    runs: list[AgentRun] = field(default_factory=list)
    skipped: list[AgentSkip] = field(default_factory=list)
    failed: list[AgentFailure] = field(default_factory=list)
    analysis_result_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    recommendation: RecommendationResult | None = None
    #: Whether the other language was produced and stored in this run. False
    #: means the reader falls back to the on-demand endpoint, which is a slower
    #: path rather than a missing feature - and reporting it is what lets the
    #: interface tell those two apart.
    translated: bool = False
    #: Which language the agents wrote in. Recorded rather than assumed, so a
    #: deployment that changes `analysis_language` leaves its older rows saying
    #: truthfully what they are instead of being relabelled by the new setting.
    language: str = "en"
    #: Per-agent renderings, keyed by agent name then by language. Produced in
    #: the same run as the analysis so switching language costs no request and
    #: no tokens - the reader is already waiting once, and paying for a
    #: rendering every time somebody flips a switch was the alternative.
    agent_translations: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The pre-analysis decision and the arithmetic behind it. Reported rather
    #: than kept internal: a run that used the cheap tier produced shallower
    #: prose for a stated reason, and a reader comparing two analyses of
    #: different issuers deserves to see which one was triaged down.
    triage: Triage | None = None

    @property
    def synthesis(self) -> AgentRun | None:
        return next((r for r in self.runs if r.agent == "summary_agent"), None)

    @property
    def analyzer_runs(self) -> list[AgentRun]:
        return [r for r in self.runs if r.agent not in _DERIVED_AGENTS]

    @property
    def total_cost(self) -> str:
        return str(sum((r.usage.cost_estimate for r in self.runs), start=Decimal("0")))

    @property
    def total_tokens(self) -> int:
        return sum(r.usage.total_tokens for r in self.runs)

    def as_payload(self) -> dict[str, Any]:
        return {
            "ticker": self.asset_ticker,
            "timeframe": self.timeframe.value,
            "agents": {
                run.agent: {
                    **run.output.model_dump(mode="json"),
                    "prompt_version": run.template_version,
                    "model": run.usage.model,
                    "provider": run.usage.provider,
                    "attempts": run.attempts,
                    "fallbacks_used": list(run.fallbacks_used),
                    # Same shape the recommendation carries, so one hook in the
                    # interface reads both: `language` says what the prose above
                    # is, `translations` holds the rendering of it.
                    "language": self.language,
                    "translations": self.agent_translations.get(run.agent, {}),
                }
                for run in self.runs
            },
            "skipped": [{"agent": s.agent, "reason": s.reason} for s in self.skipped],
            "failed": [{"agent": f.agent, "reason": f.reason} for f in self.failed],
            "usage": {"total_tokens": self.total_tokens, "estimated_cost": self.total_cost},
            "triage": self.triage.as_payload() if self.triage else None,
            "recommendation": (
                self.recommendation.as_payload() if self.recommendation else None
            ),
        }


class AnalysisEngine:
    def __init__(
        self,
        session: Session,
        gateway: LLMGateway,
        *,
        composer: PromptComposer | None = None,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        self._session = session
        self._gateway = gateway
        self._composer = composer or PromptComposer()
        self._context_builder = context_builder or ContextBuilder(session)

    def analyze(
        self,
        asset: Asset,
        timeframe: Timeframe = Timeframe.D1,
        *,
        user_id: uuid.UUID | None = None,
        persist: bool = True,
        include_recommendation: bool = True,
        #: Produce the other language in the same run. On by default: the
        #: reader is already waiting, and doing it now removes the wait from
        #: every later view. Off for callers that only want the analysis - a
        #: batch backfill, say - where the extra call buys nothing.
        translate_output: bool = True,
        #: A reader asked about this issuer by name. Skips the triage
        #: downgrade: somebody opening a stock deliberately has a reason the
        #: stored numbers do not know about, and serving them the cheap path
        #: makes the feature feel broken exactly when it is being used on
        #: purpose. Batch and scheduled callers leave this false, which is
        #: where the saving actually lives.
        requested_full: bool = False,
    ) -> AnalysisRun:
        context = self._context_builder.build(asset, timeframe, user_id=user_id)
        run = AnalysisRun(
            asset_ticker=asset.ticker,
            timeframe=timeframe,
            # Taken from the composer, which is what actually told the model
            # which language to answer in. Reading the setting again here would
            # be a second source for one fact, and the two could disagree the
            # moment a caller passes its own composer.
            language=self._composer.language.value,
        )

        conversation: AIConversation | None = None
        recorder: ConversationRecorder | None = None
        if persist and user_id is not None:
            conversation = AIConversation(
                user_id=user_id,
                context_type="asset_analysis",
                title=f"{asset.ticker} {timeframe.value}",
            )
            self._session.add(conversation)
            self._session.flush()
            recorder = ConversationRecorder(self._session, conversation.id)
            run.conversation_id = conversation.id

        # Decided before a single prompt exists, from figures the platform has
        # already computed. A full run is a dozen model calls, and without this
        # they cost the same whether the issuer moved violently or did nothing
        # at all.
        triage = triage_for(self._session, asset.ticker, requested_full=requested_full)
        run.triage = triage

        runner = AgentRunner(
            self._gateway,
            self._composer,
            recorder=recorder,
            high_privacy=context.memory.high_privacy,
            complexity_cap=triage.complexity,
        )

        for agent in (MarketAnalyzer(), TechnicalAnalyzer(), FundamentalAnalyzer(), NewsAnalyzer()):
            self._execute(agent, context, runner, run)

        # Synthesis is constructed after the analyzers so it can decide, from
        # what actually succeeded, whether there is anything to synthesise.
        self._execute(SummaryAgent(run.analyzer_runs), context, runner, run)

        # The analysis row is written before the recommendation, because a
        # recommendation is a child of one and needs its id.
        if persist:
            run.analysis_result_id = self._persist(asset, timeframe, context, run)

        if include_recommendation and run.analyzer_runs:
            self._recommend(context, runner, run, persist=persist)

            # Translated before the snapshot is written, not after. The
            # snapshot is what `GET /recommendation` reads, so storing it first
            # would leave every later view without the translation while the
            # response to *this* request carried one - the two disagreeing
            # about the same analysis.
            if persist and translate_output:
                self._render_other_language(run)

            if persist and run.analysis_result_id is not None:
                # Re-stored now that the payload includes the recommendation
                # and whatever rendering succeeded.
                self._update_snapshot(run, context)

        if persist and user_id is not None:
            self._announce(user_id, asset, run)

        return run

    def _announce(self, user_id: uuid.UUID, asset: Asset, run: AnalysisRun) -> None:
        """Tell the user the analysis finished. Never raises.

        Last, so it describes what was actually produced rather than what was
        about to be. And guarded, because a notification failing is not a
        reason to lose an analysis that succeeded - the run is already stored
        by this point and throwing here would report failure for work that is
        sitting in the database.
        """
        try:
            NotificationService(self._session).notify(
                user_id,
                NotificationEvent.ANALYSIS_READY,
                # A statement of fact. The stance goes in `context` as data,
                # for the same reason it does on alerts: a line read in
                # seconds, stripped of confidence and counter-evidence, must
                # not read as a call to act.
                f"Analysis for {asset.ticker} finished with "
                f"{len(run.runs)} agent(s) reporting.",
                context={
                    "ticker": asset.ticker,
                    "timeframe": run.timeframe.value,
                    # Here as a number rather than only inside the sentence, so
                    # a reader in another language gets the same fact composed
                    # in theirs. The stored prose is the fallback, not the
                    # source of truth for display.
                    "agents": len(run.runs),
                    "analysis_result_id": (
                        str(run.analysis_result_id) if run.analysis_result_id else None
                    ),
                    "stance": (
                        run.recommendation.output.label.value
                        if run.recommendation
                        else None
                    ),
                    "confidence": (
                        run.recommendation.calibration.confidence
                        if run.recommendation
                        else None
                    ),
                    "skipped": [s.agent for s in run.skipped],
                    "failed": [f.agent for f in run.failed],
                },
            )
        except Exception:  # noqa: BLE001 - announcing must not fail the run
            logger.warning(
                "analysis stored but not announced",
                extra={"ticker": asset.ticker, "user_id": str(user_id)},
            )

    def translate_stored(self, result: AnalysisResult) -> dict[str, Any]:
        """Render an already-stored analysis in the other language.

        Runs as its own job, after the analysis is readable. Doing it inline
        made a slow run far slower for no benefit to the person waiting: the
        result existed and was being withheld while five more model calls
        rendered a language they might never switch to - and a gateway that
        gave up part-way took the finished analysis down with it.

        Reads the stored snapshot rather than a live `AnalysisRun`, because by
        now the run that produced it is long gone.
        """
        # Deep-copied, and that is load-bearing. A shallow copy shares every
        # nested dict with the instance the ORM is holding, so editing an
        # agent's payload edits what SQLAlchemy believes is already stored -
        # and the assignment at the end then compares equal to the old value
        # and emits no UPDATE at all. The work happens, costs tokens, and is
        # silently discarded on commit.
        snapshot = copy.deepcopy(dict(result.context_snapshot or {}))
        payload = snapshot.get("result") or {}
        agents = payload.get("agents") or {}

        language = next(
            (a.get("language") for a in agents.values() if a.get("language")),
            self._composer.language.value,
        )
        target = other_language(language)

        translated_agents: list[str] = []
        for name, agent_payload in agents.items():
            fields = translatable_fields(agent_payload)
            if not fields:
                continue
            if (agent_payload.get("translations") or {}).get(target.value):
                # Already rendered by an earlier attempt. A retry must not pay
                # for the same tokens twice.
                continue
            try:
                rendered = translate(
                    self._gateway, agent_payload, target, agent=f"translate:{name}"
                )
            except (GatewayError, ValueError) as exc:
                logger.warning(
                    "agent output stored without its translation",
                    extra={"agent": name, "error": f"{type(exc).__name__}: {exc}"},
                )
                continue

            agent_payload.setdefault("translations", {})[target.value] = {
                "fields": rendered.fields,
                "model": rendered.model,
                "is_machine_translation": True,
            }
            translated_agents.append(name)

        recommendation_done = False
        row = self._session.scalar(
            select(Recommendation).where(Recommendation.analysis_result_id == result.id)
        )
        if row is not None:
            recommendation_done = render_translation(
                self._session, self._gateway, row.id
            )
            if recommendation_done and payload.get("recommendation"):
                payload["recommendation"]["translations"] = dict(row.translations or {})
                payload["recommendation"]["language"] = row.language

        if translated_agents or recommendation_done:
            # Reassigned rather than mutated: SQLAlchemy does not track in-place
            # edits to a JSON column, so the work would be silently discarded.
            payload["agents"] = agents
            snapshot["result"] = payload
            result.context_snapshot = snapshot
            self._session.flush()

        return {
            "language": target.value,
            "agents": translated_agents,
            "recommendation": recommendation_done,
        }

    def _render_other_language(self, run: AnalysisRun) -> None:
        """Produce the other language for everything a reader will look at.

        Both the recommendation and each agent's own write-up, because the
        analysis tab shows the agents and a switch that translated only the
        conclusion would leave the evidence beneath it in a language the reader
        did not ask for.

        Done here, once, rather than on demand: the reader is already waiting
        for the analysis, and the alternative was paying a model call every
        time somebody flipped a switch on text that cannot change.
        """
        self._translate_agents(run)

        recommendation_id = (
            run.recommendation.recommendation_id if run.recommendation else None
        )
        if recommendation_id is None:
            return
        run.translated = render_translation(
            self._session, self._gateway, recommendation_id
        )
        if run.translated and run.recommendation is not None:
            # Read back rather than reconstructed, so the payload carries what
            # was actually stored. A response describing a translation the
            # database does not hold would send the reader to a switch that
            # then had nothing behind it.
            row = self._session.get(Recommendation, recommendation_id)
            if row is not None:
                run.recommendation.language = row.language
                run.recommendation.translations = dict(row.translations or {})

    def _translate_agents(self, run: AnalysisRun) -> None:
        """Render each agent's prose in the other language. Never raises.

        One call per agent rather than one call for all of them. Batching would
        be cheaper, but `translate` refuses a response that dropped a key - and
        with every agent in one payload, a single omission would discard the
        whole set. Per agent, a failure costs that agent's rendering and
        nothing else.
        """
        target = other_language(run.language)
        for agent_run in run.runs:
            payload = agent_run.output.model_dump(mode="json")
            if not translatable_fields(payload):
                # Nothing but labels and numbers. A call here would spend
                # tokens to return what it was given.
                continue
            try:
                rendered = translate(
                    self._gateway, payload, target, agent=f"translate:{agent_run.agent}"
                )
            except (GatewayError, ValueError) as exc:
                # The analysis is the product; this is a convenience. Losing a
                # completed multi-agent run to a rendering step would be a bad
                # trade in every direction.
                logger.warning(
                    "agent output stored without its translation",
                    extra={
                        "agent": agent_run.agent,
                        "language": target.value,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                continue

            run.agent_translations.setdefault(agent_run.agent, {})[target.value] = {
                "fields": rendered.fields,
                "model": rendered.model,
                "is_machine_translation": True,
            }

    def _recommend(
        self,
        context: AnalysisContext,
        runner: AgentRunner,
        run: AnalysisRun,
        *,
        persist: bool,
    ) -> None:
        engine = RecommendationEngine(self._session, runner)
        try:
            run.recommendation = engine.generate(
                context,
                run.analyzer_runs,
                run.synthesis,
                analysis_result_id=run.analysis_result_id,
                persist=persist,
            )
            run.runs.append(run.recommendation.run)
        except RecommendationRejected as exc:
            # The rules of Section 14.4 were not met even after correction.
            # Recorded as a failure rather than stored with a caveat: a
            # recommendation whose evidence has not been weighed should not
            # reach a user at all.
            run.failed.append(
                AgentFailure(
                    agent="recommendation_agent",
                    reason=f"rejected by Section 14.4 rules: {exc}",
                )
            )
        except ValidationFailure as exc:
            run.failed.append(
                AgentFailure(
                    agent="recommendation_agent", reason=f"output validation failed: {exc}"
                )
            )
        except GatewayError as exc:
            run.failed.append(AgentFailure(agent="recommendation_agent", reason=str(exc)))

    def _update_snapshot(self, run: AnalysisRun, context: AnalysisContext) -> None:
        result = self._session.get(AnalysisResult, run.analysis_result_id)
        if result is None:
            return
        result.context_snapshot = {
            "context": context.snapshot(),
            "result": run.as_payload(),
        }
        self._session.flush()

    def _execute(
        self,
        agent: Agent,
        context: AnalysisContext,
        runner: AgentRunner,
        run: AnalysisRun,
    ) -> None:
        if not agent.is_applicable(context):
            run.skipped.append(AgentSkip(agent=agent.name, reason=agent.skip_reason(context)))
            return
        try:
            run.runs.append(runner.run(agent, context))
        except ValidationFailure as exc:
            # The model could not produce a valid answer even after correction.
            run.failed.append(
                AgentFailure(agent=agent.name, reason=f"output validation failed: {exc}")
            )
        except GatewayError as exc:
            run.failed.append(AgentFailure(agent=agent.name, reason=str(exc)))

    def _persist(
        self,
        asset: Asset,
        timeframe: Timeframe,
        context: AnalysisContext,
        run: AnalysisRun,
    ) -> uuid.UUID:
        synthesis = run.synthesis
        primary = synthesis or (run.runs[0] if run.runs else None)

        result = AnalysisResult(
            asset_id=asset.id,
            analysis_type="multi_agent",
            # Carried onto the row so the requester is answerable later, not
            # only while this call is on the stack.
            conversation_id=run.conversation_id,
            model_used=primary.usage.model if primary else None,
            prompt_version=primary.template_version if primary else None,
            # The context snapshot plus the per-agent prompt versions are what
            # make this row reproducible rather than merely readable.
            context_snapshot={
                "context": context.snapshot(),
                "result": run.as_payload(),
            },
        )
        self._session.add(result)
        self._session.flush()
        return result.id
