"""Executable enforcement of the architecture's hard constraint.

The planning document states repeatedly (Sections 1, 2.3, 3, 4, 8, 10) that
this platform has no path to order execution - not a disabled module, but one
that was never designed or built. A statement in a document degrades over
time; a failing test does not. These checks fail the build the moment anyone
introduces an order table, a broker adapter, or an execution endpoint.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aidss.db.base import Base
from aidss.main import create_app
from aidss.plugins.registry import registry_snapshot

SRC = Path(__file__).resolve().parents[1] / "src" / "aidss"

#: Table names that would betray the constraint if they ever appeared.
FORBIDDEN_TABLES = {"orders", "executions", "brokers", "trades", "order_items", "positions_live"}

#: Route path fragments that would mean the API can act on a trading account.
FORBIDDEN_ROUTE_FRAGMENTS = ("/order", "/execute", "/execution", "/broker", "/trade")

#: Identifiers that only exist in code capable of placing or cancelling orders.
#: Written as word-boundary patterns so ordinary vocabulary - `order_by`,
#: `ordering`, `reorder`, `execute()` on a SQL session - is not caught.
FORBIDDEN_IDENTIFIERS = (
    r"\bplace_order\b",
    r"\bsubmit_order\b",
    r"\bcancel_order\b",
    r"\bsend_order\b",
    r"\bexecute_order\b",
    r"\bexecute_trade\b",
    r"\bplace_trade\b",
    r"\bBrokerAdapter\b",
    r"\bBrokerProvider\b",
    r"\bExecutionEngine\b",
    r"\bOrderRouter\b",
    r"\btrading_api\b",
)


def source_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_source_tree_is_not_empty() -> None:
    """Guards the guard: a broken path would make every check below vacuous."""
    assert len(source_files()) > 20


def test_no_order_or_broker_tables_exist() -> None:
    tables = set(Base.metadata.tables)
    assert not (tables & FORBIDDEN_TABLES), (
        f"Forbidden tables present: {sorted(tables & FORBIDDEN_TABLES)}. "
        "This platform is decision-support only (Section 8.2)."
    )


def test_no_execution_endpoints_are_exposed() -> None:
    # Read the OpenAPI schema rather than `app.routes`: it is the authoritative
    # list of what is actually reachable, and it is not affected by however
    # FastAPI happens to represent included routers internally.
    paths = [path.lower() for path in create_app().openapi()["paths"]]
    # Sanity check, so a change in how paths are collected cannot quietly turn
    # this test into one that asserts nothing.
    assert "/auth/login" in paths
    offending = [
        path
        for path in paths
        for fragment in FORBIDDEN_ROUTE_FRAGMENTS
        if fragment in path
    ]
    assert not offending, f"Forbidden endpoints exposed: {offending} (Section 10)."


@pytest.mark.parametrize("pattern", FORBIDDEN_IDENTIFIERS)
def test_no_execution_identifiers_in_source(pattern: str) -> None:
    regex = re.compile(pattern)
    hits = [
        f"{path.relative_to(SRC)}:{number}"
        for path in source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if regex.search(line)
    ]
    assert not hits, f"Pattern {pattern} found at {hits}; execution paths are out of scope."


def test_no_broker_adapter_is_registered() -> None:
    """The plugin registry has four kinds, and none of them is a broker."""
    kinds = set(registry_snapshot())
    assert kinds <= {"market_data", "news", "ai", "storage"}
    assert "broker" not in kinds
    assert "execution" not in kinds


def test_portfolio_input_method_has_no_broker_sync_option() -> None:
    """Portfolio data is user-entered; the enum must offer no other origin."""
    from aidss.db.models import HoldingInputMethod

    assert {member.value for member in HoldingInputMethod} == {"manual", "import"}


def test_recommendation_labels_are_not_execution_instructions() -> None:
    """Labels describe a stance, never a command (Section 5.4)."""
    from aidss.db.models import RecommendationLabel

    assert {member.value for member in RecommendationLabel} == {
        "strong_buy",
        "buy",
        "watchlist",
        "hold",
        "reduce",
        "sell",
    }


def test_stop_loss_field_is_named_as_a_suggestion() -> None:
    """Section 5.4 requires the stop level be labelled a suggestion, not an order."""
    from aidss.db.models import Recommendation

    columns = set(Recommendation.__table__.columns.keys())
    assert "suggested_stop" in columns
    assert "stop_loss_order" not in columns


def test_recommendation_requires_conflicting_factors_column() -> None:
    """Guards against confirmation bias by construction (Section 5.4)."""
    from aidss.db.models import Recommendation

    assert "conflicting_factors" in Recommendation.__table__.columns


def test_agent_output_models_reject_unknown_fields() -> None:
    """A schema that ignores extras is a schema a drifting prompt can widen.

    With `extra="forbid"`, a model that starts emitting an `order` or
    `execute` field fails validation loudly instead of having it silently
    dropped and never noticed.
    """
    from aidss.prompts.schemas import OUTPUT_MODELS

    assert OUTPUT_MODELS, "no agent output models registered"
    for name, model in OUTPUT_MODELS.items():
        assert model.model_config.get("extra") == "forbid", f"{name} accepts extra fields"


def test_ai_provider_interface_exposes_no_write_capability() -> None:
    """Section 12.4: the AI layer's surface is read-only by construction.

    Even a successful prompt injection has nothing to act on, because no
    action-taking method exists to be called.
    """
    from aidss.plugins.interfaces import AIProvider

    public = {n for n in dir(AIProvider) if not n.startswith("_")}
    forbidden = {"execute", "run_tool", "call_tool", "invoke", "submit", "send"}
    assert not (public & forbidden), f"AIProvider exposes {public & forbidden}"


def test_every_prompt_template_states_the_language_rule() -> None:
    """Enforced twice on purpose: in the prompt, and on the output."""
    from aidss.prompts import catalog
    from aidss.prompts.language import LANGUAGE_RULE

    assert catalog.ALL_TEMPLATES
    for template in catalog.ALL_TEMPLATES:
        assert LANGUAGE_RULE in template.render_system("{}"), template.name


def test_portfolio_simulation_cannot_write_a_holding() -> None:
    """A simulation that mutated the portfolio would turn a question into a decision.

    The module operates on plain dataclasses and has no database session, so
    persistence is not merely avoided - it is unreachable.
    """
    text = (SRC / "portfolio" / "simulation.py").read_text(encoding="utf-8")
    for forbidden in ("Session", "session.add", "session.commit", "PortfolioHolding"):
        assert forbidden not in text, f"simulation.py references {forbidden}"


def test_portfolio_agents_are_marked_sensitive() -> None:
    """Positions are personal financial data (Sections 12.10, 13).

    Marking it on the agent rather than at the call site means the next
    endpoint to use them cannot forget.
    """
    from aidss.llm.router import Sensitivity
    from aidss.portfolio.agents import PortfolioAnalyzer, RiskAnalyzer

    assert PortfolioAnalyzer.sensitivity is Sensitivity.SENSITIVE
    assert RiskAnalyzer.sensitivity is Sensitivity.SENSITIVE


def test_the_recommendation_schema_has_no_price_field() -> None:
    """A price stated by a language model is a number nobody measured.

    Section 5.4's price fields are derived from the Indicator Engine and
    attached afterwards. The model's schema must therefore offer nowhere to put
    one - with `extra="forbid"`, that makes it structurally impossible rather
    than merely discouraged.
    """
    from aidss.prompts.schemas import RecommendationOutput

    fields = set(RecommendationOutput.model_fields)
    price_fields = {"target_price", "support_level", "resistance_level", "suggested_stop", "price"}
    assert not (fields & price_fields), f"model can state prices: {fields & price_fields}"
    assert RecommendationOutput.model_config.get("extra") == "forbid"


def test_the_stored_confidence_column_is_range_checked() -> None:
    """Section 5.4 puts confidence on a 0-100 scale; the database enforces it."""
    from aidss.db.models import Recommendation

    constraints = {
        c.name for c in Recommendation.__table__.constraints if c.name is not None
    }
    assert "ck_confidence_range" in constraints


def test_enum_columns_store_values_not_member_names() -> None:
    """One fact must not be written two ways inside one database.

    SQLAlchemy defaults to persisting the member *name* (``WATCHLIST``) while
    the API, the JSON snapshots, and every StrEnum comparison in the code use
    the *value* (``watchlist``). A dashboard filtering ``WHERE label = 'buy'``
    would then silently return nothing.
    """
    from sqlalchemy import Enum as SAEnum

    from aidss.db.base import Base

    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, SAEnum) or column.type.enum_class is None:
                continue
            stored = set(column.type.enums)
            expected = {m.value for m in column.type.enum_class}
            if stored != expected:
                offenders.append(f"{table.name}.{column.name} stores {sorted(stored)}")

    assert not offenders, "enum columns storing member names: " + "; ".join(offenders)


def test_recommendation_labels_are_defined_once() -> None:
    """Two copies of a vocabulary drift apart; the database and the prompt
    schema must be reading from the same enum."""
    from aidss.db.models import RecommendationLabel as db_label
    from aidss.domain.types import RecommendationLabel as domain_label

    assert db_label is domain_label


def test_every_section_10_endpoint_exists() -> None:
    """The planning document's API surface, checked rather than assumed.

    Three of these were missing after the nine phases were "done" - the kind of
    gap a phase-by-phase reading does not surface, because no single phase owns
    the endpoint list.
    """
    paths = set(create_app().openapi()["paths"])

    for required in (
        "/auth/login",
        "/assets/{ticker}/analysis",
        "/assets/{ticker}/recommendation",
        "/portfolio",
        "/portfolio/analysis",
        "/portfolio/simulate",
        "/watchlist",
        "/journal",
        "/chat",
        "/knowledge-base",
        "/news-schedules",
        "/news-schedules/{schedule_id}/run-now",
        "/assets/{ticker}/news",
        "/providers",
        "/audit-logs",
    ):
        assert required in paths, f"Section 10 endpoint missing: {required}"


def test_every_section_5_2_agent_exists() -> None:
    """The agent roster from Section 5.2, checked the same way."""
    from aidss.prompts.schemas import OUTPUT_MODELS

    expected = {
        "market_analyzer",
        "technical_analyzer",
        "fundamental_analyzer",
        "news_analyzer",
        "research_agent",
        "portfolio_analyzer",
        "risk_analyzer",
        "knowledge_agent",
        "reflection_agent",
        "summary_agent",
    }
    assert expected <= set(OUTPUT_MODELS), (
        f"agents missing: {sorted(expected - set(OUTPUT_MODELS))}"
    )


def test_no_notification_event_can_carry_an_instruction() -> None:
    """Section 9: alerts are about the system, never about what to do with money.

    The event vocabulary is a closed enum, so no future caller can invent an
    instruction-shaped event by passing a different string.
    """
    from aidss.reporting.notifications import SUBJECTS, NotificationEvent

    assert set(SUBJECTS) == set(NotificationEvent)
    for event in NotificationEvent:
        text = f"{event.value} {SUBJECTS[event]}".lower()
        for word in ("buy", "sell", "trade", "order", "execute"):
            assert word not in text, f"{event.value} reads as an instruction"


def test_every_investor_facing_response_carries_a_disclaimer() -> None:
    """Section 2.7 requires it consistently, not on whichever route remembered."""
    from aidss.api.routes.analysis import ANALYSIS_DISCLAIMER
    from aidss.api.routes.assets import DISCLAIMER as INDICATOR_DISCLAIMER
    from aidss.api.routes.portfolio import PORTFOLIO_DISCLAIMER
    from aidss.reporting.builder import REPORT_DISCLAIMER

    for name, text in (
        ("analysis", ANALYSIS_DISCLAIMER),
        ("indicators", INDICATOR_DISCLAIMER),
        ("portfolio", PORTFOLIO_DISCLAIMER),
        ("report", REPORT_DISCLAIMER),
    ):
        lowered = text.lower()
        assert "not investment advice" in lowered, f"{name} disclaimer is incomplete"
        assert (
            "place an order" in lowered or "places orders" in lowered
        ), f"{name} disclaimer does not state the execution limit"


def test_credentials_cannot_reach_the_logs() -> None:
    """Section 13, enforced rather than trusted to every future caller."""
    from aidss.observability.logging import REDACTED, redact

    for secret in (
        "sk-abcdef1234567890",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload",
        "postgresql://user:hunter2@db:5432/aidss",
    ):
        cleaned = redact(secret)
        assert REDACTED in cleaned or "hunter2" not in cleaned
    assert redact({"api_key": "sk-live"})["api_key"] == REDACTED


def test_indicator_engine_does_not_import_any_ai_provider() -> None:
    """Numeric work stays deterministic and LLM-free (Section 2.7, 5.3)."""
    indicator_sources = (SRC / "indicators").rglob("*.py")
    for path in indicator_sources:
        text = path.read_text(encoding="utf-8")
        assert "AIProvider" not in text, f"{path.name} must not depend on an AI provider"
        assert "chat_completion" not in text, f"{path.name} must not call an LLM"
