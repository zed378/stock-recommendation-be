"""Analysis Engine - multi-agent orchestration (Section 5.1).

Runs the flow of the Section 5.1 diagram as far as Phase 4 goes: build context,
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

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

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
from aidss.db.models import AIConversation, AnalysisResult, Asset, Recommendation
from aidss.domain.types import Timeframe
from aidss.llm.errors import GatewayError
from aidss.llm.gateway import LLMGateway
from aidss.prompts.manager import PromptComposer
from aidss.prompts.validator import ValidationFailure
from aidss.recommendations.engine import (
    RecommendationEngine,
    RecommendationRejected,
    RecommendationResult,
)
from aidss.recommendations.rendering import render_translation


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
                }
                for run in self.runs
            },
            "skipped": [{"agent": s.agent, "reason": s.reason} for s in self.skipped],
            "failed": [{"agent": f.agent, "reason": f.reason} for f in self.failed],
            "usage": {"total_tokens": self.total_tokens, "estimated_cost": self.total_cost},
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
    ) -> AnalysisRun:
        context = self._context_builder.build(asset, timeframe, user_id=user_id)
        run = AnalysisRun(asset_ticker=asset.ticker, timeframe=timeframe)

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

        runner = AgentRunner(
            self._gateway,
            self._composer,
            recorder=recorder,
            high_privacy=context.memory.high_privacy,
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

        return run

    def _render_other_language(self, run: AnalysisRun) -> None:
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
            # The rules of Section 5.4 were not met even after correction.
            # Recorded as a failure rather than stored with a caveat: a
            # recommendation whose evidence has not been weighed should not
            # reach a user at all.
            run.failed.append(
                AgentFailure(
                    agent="recommendation_agent",
                    reason=f"rejected by Section 5.4 rules: {exc}",
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
