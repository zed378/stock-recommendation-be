"""Portfolio Intelligence engine (Phase 6, Section 14.2, 9).

Builds the portfolio context, runs the two analyzers, and persists the result
to ``portfolio_analysis`` and ``risk_assessments``.

Same failure policy as the asset engine: an analyzer with nothing to work on is
skipped with its reason, one that breaks does not take the other down, and
neither can be confused with the other in the output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aidss.agents.base import Agent, AgentRun, AgentRunner, AgentSkip, ConversationRecorder
from aidss.agents.memory import MemoryManager
from aidss.db.models import AIConversation, Portfolio, PortfolioAnalysis, RiskAssessment
from aidss.llm.errors import GatewayError
from aidss.llm.gateway import LLMGateway
from aidss.portfolio.agents import PortfolioAnalyzer, PortfolioContext, RiskAnalyzer
from aidss.portfolio.loader import load_positions, load_price_series
from aidss.portfolio.metrics import compute_portfolio_metrics, correlation_matrix
from aidss.portfolio.risk import portfolio_risk
from aidss.prompts.manager import PromptComposer
from aidss.prompts.validator import ValidationFailure


@dataclass(slots=True)
class PortfolioAnalysisRun:
    portfolio_name: str
    context: PortfolioContext
    runs: list[AgentRun] = field(default_factory=list)
    skipped: list[AgentSkip] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    portfolio_analysis_id: uuid.UUID | None = None
    risk_assessment_id: uuid.UUID | None = None

    def agent(self, name: str) -> AgentRun | None:
        return next((r for r in self.runs if r.agent == name), None)

    def as_payload(self) -> dict[str, Any]:
        return {
            "portfolio": self.portfolio_name,
            "metrics": self.context.metrics.as_dict() if self.context.metrics else {},
            "risk": self.context.risk.as_dict() if self.context.risk else {},
            "correlation": self.context.correlation,
            "holdings": self.context.holdings_payload(),
            "agents": {
                run.agent: {
                    **run.output.model_dump(mode="json"),
                    "prompt_version": run.template_version,
                    "model": run.usage.model,
                    "provider": run.usage.provider,
                }
                for run in self.runs
            },
            "skipped": [{"agent": s.agent, "reason": s.reason} for s in self.skipped],
            "failed": list(self.failed),
        }


class PortfolioIntelligenceEngine:
    def __init__(
        self,
        session: Session,
        gateway: LLMGateway,
        *,
        composer: PromptComposer | None = None,
    ) -> None:
        self._session = session
        self._gateway = gateway
        self._composer = composer or PromptComposer()

    def build_context(self, portfolio: Portfolio, user_id: uuid.UUID | None) -> PortfolioContext:
        """Compute every figure before a single prompt is composed."""
        positions = load_positions(self._session, portfolio)
        series = load_price_series(self._session, positions)

        return PortfolioContext(
            portfolio_name=portfolio.name,
            base_currency=portfolio.base_currency,
            memory=MemoryManager(self._session).load(user_id),
            positions=positions,
            metrics=compute_portfolio_metrics(positions),
            risk=portfolio_risk(positions, series) if positions else None,
            correlation=correlation_matrix(series),
        )

    def analyze(
        self,
        portfolio: Portfolio,
        *,
        user_id: uuid.UUID | None = None,
        persist: bool = True,
    ) -> PortfolioAnalysisRun:
        context = self.build_context(portfolio, user_id)
        run = PortfolioAnalysisRun(portfolio_name=portfolio.name, context=context)

        recorder: ConversationRecorder | None = None
        if persist and user_id is not None:
            conversation = AIConversation(
                user_id=user_id,
                context_type="portfolio_analysis",
                title=f"Portfolio {portfolio.name}",
            )
            self._session.add(conversation)
            self._session.flush()
            recorder = ConversationRecorder(self._session, conversation.id)

        runner = AgentRunner(
            self._gateway,
            self._composer,
            recorder=recorder,
            high_privacy=context.memory.high_privacy,
        )

        for agent in (PortfolioAnalyzer(), RiskAnalyzer()):
            self._execute(agent, context, runner, run)

        if persist:
            self._persist(portfolio, context, run)
        return run

    def _execute(
        self,
        agent: Agent,
        context: PortfolioContext,
        runner: AgentRunner,
        run: PortfolioAnalysisRun,
    ) -> None:
        if not agent.is_applicable(context):
            run.skipped.append(AgentSkip(agent=agent.name, reason=agent.skip_reason(context)))
            return
        try:
            run.runs.append(runner.run(agent, context))
        except ValidationFailure as exc:
            run.failed.append(
                {"agent": agent.name, "reason": f"output validation failed: {exc}"}
            )
        except GatewayError as exc:
            run.failed.append({"agent": agent.name, "reason": str(exc)})

    def _persist(
        self, portfolio: Portfolio, context: PortfolioContext, run: PortfolioAnalysisRun
    ) -> None:
        metrics = context.metrics
        portfolio_run = run.agent("portfolio_analyzer")

        analysis = PortfolioAnalysis(
            portfolio_id=portfolio.id,
            diversification_score=metrics.diversification_score if metrics else None,
            sector_concentration=(
                {k: round(v, 6) for k, v in metrics.sector_weights.items()} if metrics else {}
            ),
            correlation_matrix=context.correlation,
            narrative=portfolio_run.output.summary if portfolio_run else None,
        )
        self._session.add(analysis)
        self._session.flush()
        run.portfolio_analysis_id = analysis.id

        if context.risk is not None and context.risk.observations > 0:
            assessment = RiskAssessment(
                portfolio_id=portfolio.id,
                risk_type="portfolio_historical",
                # Stored as annualised volatility rather than a synthesised
                # 0-100 "risk score": an invented composite would look
                # authoritative while meaning whatever its weights happened to
                # be. The full breakdown lives in `detail`.
                score=context.risk.annualised_volatility or 0.0,
                detail=run.as_payload()["risk"],
            )
            self._session.add(assessment)
            self._session.flush()
            run.risk_assessment_id = assessment.id
