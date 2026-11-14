"""TradingAgents multi-agent debate pipeline integrated with AIDSS."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from aidss.agents.base import AgentRun, AgentRunner
from aidss.agents.context import AnalysisContext
from aidss.agents.trading_agents.decision_memory import (
    load_past_lessons,
    record_decision,
    settle_pending_decisions,
)
from aidss.agents.trading_agents.researchers import ResearchDebateResult, run_research_debate
from aidss.agents.trading_agents.risk_mgmt import RiskDebateResult, run_risk_debate
from aidss.agents.trading_agents.trader import TraderAgent
from aidss.prompts.schemas import (
    PortfolioManagerOutput,
    ResearchManagerOutput,
    TraderProposalOutput,
)


@dataclass(slots=True)
class TradingAgentsTrace:
    """Full structured trace of the TradingAgents debate & decision pipeline."""

    research_debate: ResearchDebateResult
    trader_run: AgentRun
    risk_debate: RiskDebateResult
    past_lessons: list[dict[str, Any]] = field(default_factory=list)
    decision_log_id: uuid.UUID | None = None

    @property
    def all_runs(self) -> list[AgentRun]:
        runs: list[AgentRun] = []
        runs.extend(self.research_debate.turns)
        if self.research_debate.manager_run is not None:
            runs.append(self.research_debate.manager_run)
        runs.append(self.trader_run)
        runs.extend(self.risk_debate.turns)
        if self.risk_debate.manager_run is not None:
            runs.append(self.risk_debate.manager_run)
        return runs

    def as_payload(self) -> dict[str, Any]:
        rm_out = (
            self.research_debate.manager_run.output.model_dump(mode="json")
            if self.research_debate.manager_run
            else None
        )
        pm_out = (
            self.risk_debate.manager_run.output.model_dump(mode="json")
            if self.risk_debate.manager_run
            else None
        )
        return {
            "decision_log_id": str(self.decision_log_id) if self.decision_log_id else None,
            "research_debate": self.research_debate.history,
            "research_manager": rm_out,
            "trader_proposal": self.trader_run.output.model_dump(mode="json"),
            "risk_debate": self.risk_debate.history,
            "portfolio_manager": pm_out,
            "past_lessons": self.past_lessons,
        }


class TradingAgentsPipeline:
    """Runs Bull/Bear Debate -> Research Manager -> Trader -> Risk Debate -> Portfolio Manager."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        runner: AgentRunner,
        context: AnalysisContext,
        analyzer_runs: list[AgentRun],
        *,
        user_id: uuid.UUID | None = None,
        analysis_result_id: uuid.UUID | None = None,
        max_debate_rounds: int = 2,
        max_risk_rounds: int = 1,
        persist: bool = True,
    ) -> TradingAgentsTrace:
        # Settle any matured prior decisions on this asset first (look-ahead safe)
        if persist:
            settle_pending_decisions(
                self._session,
                context.asset,
                runner=runner,
                context=context,
            )

        past_lessons = load_past_lessons(
            self._session, context.asset.id, context.asset.ticker
        )

        research_debate = run_research_debate(
            runner,
            context,
            analyzer_runs,
            max_rounds=max_debate_rounds,
        )
        assert research_debate.manager_run is not None

        trader_run = runner.run(
            TraderAgent(analyzer_runs, research_debate.manager_run),
            context,
        )

        risk_debate = run_risk_debate(
            runner,
            context,
            trader_run,
            past_lessons,
            max_rounds=max_risk_rounds,
        )
        assert risk_debate.manager_run is not None

        trace = TradingAgentsTrace(
            research_debate=research_debate,
            trader_run=trader_run,
            risk_debate=risk_debate,
            past_lessons=past_lessons,
        )

        if persist:
            rm_out: ResearchManagerOutput = research_debate.manager_run.output  # type: ignore[assignment]
            tr_out: TraderProposalOutput = trader_run.output  # type: ignore[assignment]
            pm_out: PortfolioManagerOutput = risk_debate.manager_run.output  # type: ignore[assignment]
            last_close = context.indicator_snapshot.get("last_close")
            entry_price = Decimal(str(last_close)) if last_close is not None else None
            log_row = record_decision(
                self._session,
                user_id=user_id,
                asset=context.asset,
                analysis_result_id=analysis_result_id,
                final_rating=pm_out.final_rating,
                confidence=pm_out.confidence,
                entry_price=entry_price,
                investment_plan=rm_out.investment_plan,
                trader_proposal=tr_out.thesis,
                portfolio_decision=pm_out.decision_summary,
                debate_trace=trace.as_payload(),
            )
            trace.decision_log_id = log_row.id

        return trace
