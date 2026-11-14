"""TradingAgents multi-agent debate, risk committee, and reflection modules."""

from aidss.agents.trading_agents.decision_memory import (
    DecisionReflector,
    load_past_lessons,
    record_decision,
    settle_pending_decisions,
)
from aidss.agents.trading_agents.pipeline import TradingAgentsPipeline, TradingAgentsTrace
from aidss.agents.trading_agents.researchers import (
    BearResearcher,
    BullResearcher,
    ResearchDebateResult,
    ResearchManager,
    run_research_debate,
)
from aidss.agents.trading_agents.risk_mgmt import (
    AggressiveRiskAnalyst,
    ConservativeRiskAnalyst,
    NeutralRiskAnalyst,
    PortfolioManager,
    RiskDebateResult,
    run_risk_debate,
)
from aidss.agents.trading_agents.trader import TraderAgent

__all__ = [
    "AggressiveRiskAnalyst",
    "BearResearcher",
    "BullResearcher",
    "ConservativeRiskAnalyst",
    "DecisionReflector",
    "NeutralRiskAnalyst",
    "PortfolioManager",
    "ResearchDebateResult",
    "ResearchManager",
    "RiskDebateResult",
    "TraderAgent",
    "TradingAgentsPipeline",
    "TradingAgentsTrace",
    "load_past_lessons",
    "record_decision",
    "run_research_debate",
    "run_risk_debate",
    "settle_pending_decisions",
]
