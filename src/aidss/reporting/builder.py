"""Report composition (Phase 8, Section 9 - Reporting).

Turns stored analysis into a document a person can read end to end. Reports are
assembled from what was already persisted rather than by re-running agents:
opening a report should not cost money, and a report that regenerated itself
would show different text each time it was opened - which makes it useless as a
record of what was said.

Markdown is the output format. It renders in a browser, pastes into an email,
converts to PDF with any external tool, and diffs cleanly - none of which is
true of a PDF generated in-process, which would also add a heavyweight
dependency for a format nobody can inspect.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import AnalysisResult, Asset, Portfolio, PortfolioAnalysis, Recommendation
from aidss.portfolio.engine import PortfolioIntelligenceEngine
from aidss.portfolio.loader import load_positions, load_price_series
from aidss.portfolio.metrics import compute_portfolio_metrics
from aidss.portfolio.risk import portfolio_risk

REPORT_DISCLAIMER = (
    "This report is AI-generated analysis for informational purposes only. Every "
    "indicator, metric, and risk figure in it was computed deterministically; the "
    "narrative around them was produced by a language model. Risk figures are "
    "historical and describe what has happened, not what will. This is not "
    "investment advice from a licensed adviser. Any decision to buy or sell is "
    "yours, made outside this system - the platform cannot place an order."
)


class ReportNotAvailable(LookupError):
    """There is nothing stored to build a report from."""


@dataclass(slots=True)
class Report:
    title: str
    generated_at: datetime
    markdown: str
    #: The same content as data, for a UI that wants to lay it out itself.
    payload: dict[str, Any]


def _heading(text: str, level: int = 2) -> str:
    return f"{'#' * level} {text}\n"


def _table(rows: list[tuple[str, Any]]) -> str:
    lines = ["| | |", "|---|---|"]
    lines.extend(f"| {label} | {'—' if value is None else value} |" for label, value in rows)
    return "\n".join(lines) + "\n"


def _bullets(items: list[str], *, empty: str = "_none reported_") -> str:
    if not items:
        return f"{empty}\n"
    return "\n".join(f"- {item}" for item in items) + "\n"


def _percent(value: Any, digits: int = 2) -> str | None:
    if value is None:
        return None
    return f"{float(value) * 100:.{digits}f}%"


# ---------------------------------------------------------------------------
# Asset report
# ---------------------------------------------------------------------------


def build_asset_report(session: Session, asset: Asset) -> Report:
    result = session.scalar(
        select(AnalysisResult)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(AnalysisResult.generated_at.desc())
    )
    if result is None:
        raise ReportNotAvailable(
            f"No analysis stored for {asset.ticker}. Run one before requesting a report."
        )

    snapshot = result.context_snapshot or {}
    context = snapshot.get("context", {})
    stored = snapshot.get("result", {})
    agents = stored.get("agents", {})
    recommendation = stored.get("recommendation")

    parts: list[str] = [
        f"# {asset.ticker} — analysis report\n",
        f"_Generated {result.generated_at.isoformat()} · "
        f"model {result.model_used or 'unknown'} · "
        f"prompt version {result.prompt_version or 'unknown'}_\n",
    ]

    indicators = context.get("indicators", {})
    if indicators:
        parts.append(_heading("Market snapshot"))
        parts.append(
            _table(
                [
                    ("As of", indicators.get("as_of")),
                    ("Last close", indicators.get("last_close")),
                    ("Market structure", indicators.get("structure")),
                    ("Breakout", (indicators.get("breakout") or {}).get("direction")),
                    ("Bars analysed", context.get("bars")),
                ]
            )
        )

    if recommendation:
        parts.append(_heading("Recommendation"))
        parts.append(
            _table(
                [
                    ("Label", f"**{recommendation['label'].replace('_', ' ').title()}**"),
                    ("Confidence", f"{recommendation['confidence']} / 100"),
                    ("Horizon", recommendation["horizon"]),
                    ("Support", recommendation.get("support_level")),
                    ("Resistance", recommendation.get("resistance_level")),
                    ("Target price", recommendation.get("target_price")),
                    ("Suggested stop", recommendation.get("suggested_stop")),
                ]
            )
        )
        # How the score was reached, not just the score. A confidence a reader
        # cannot interrogate is one they cannot weigh.
        basis = recommendation.get("confidence_basis", {})
        if basis.get("explanation"):
            parts.append(f"\n_{basis['explanation']}_\n")

        parts.append(_heading("Reasoning", 3))
        parts.append(f"{recommendation['reasoning']}\n")

        parts.append(_heading("Supporting", 3))
        parts.append(_bullets(recommendation.get("supporting_factors", [])))
        # Printed with equal prominence, deliberately: a report that buries the
        # counter-evidence is an argument rather than an analysis.
        parts.append(_heading("Arguing against", 3))
        parts.append(_bullets(recommendation.get("conflicting_factors", [])))
        parts.append(_heading("Risks", 3))
        parts.append(_bullets(recommendation.get("risk_factors", [])))

        parts.append(_heading("Scenarios", 3))
        parts.append(f"**If it goes up.** {recommendation['bullish_scenario']}\n")
        parts.append(f"\n**If it goes down.** {recommendation['bearish_scenario']}\n")

    if agents:
        parts.append(_heading("Analyst readings"))
        for name, output in agents.items():
            if name == "recommendation_agent":
                continue
            label = name.replace("_", " ").title()
            sufficiency = output.get("data_sufficiency", "unknown")
            parts.append(
                f"\n**{label}** · confidence {output.get('confidence', '—')} · "
                f"data {sufficiency}\n\n{output.get('summary', '')}\n"
            )

    skipped = stored.get("skipped", [])
    if skipped:
        # Named explicitly: what was *not* examined is part of the finding.
        parts.append(_heading("Not covered"))
        parts.append(_bullets([f"{s['agent'].replace('_', ' ')}: {s['reason']}" for s in skipped]))

    parts.append(f"\n---\n\n_{REPORT_DISCLAIMER}_\n")

    return Report(
        title=f"{asset.ticker} — analysis report",
        generated_at=result.generated_at,
        markdown="\n".join(parts),
        payload={
            "ticker": asset.ticker,
            "analysis_result_id": str(result.id),
            "generated_at": result.generated_at.isoformat(),
            "recommendation": recommendation,
            "agents": agents,
            "skipped": skipped,
            "context": context,
            "disclaimer": REPORT_DISCLAIMER,
        },
    )


# ---------------------------------------------------------------------------
# Portfolio report
# ---------------------------------------------------------------------------


def build_portfolio_report(
    session: Session, portfolio: Portfolio, *, user_id: uuid.UUID | None = None
) -> Report:
    positions = load_positions(session, portfolio)
    if not positions:
        raise ReportNotAvailable("The portfolio has no holdings to report on.")

    metrics = compute_portfolio_metrics(positions)
    risk = portfolio_risk(positions, load_price_series(session, positions))

    stored = session.scalar(
        select(PortfolioAnalysis)
        .where(PortfolioAnalysis.portfolio_id == portfolio.id)
        .order_by(PortfolioAnalysis.simulated_at.desc())
    )

    generated_at = datetime.now(UTC)
    parts: list[str] = [
        f"# Portfolio report — {portfolio.name}\n",
        f"_Generated {generated_at.isoformat()} · {portfolio.base_currency}_\n",
        _heading("Position summary"),
        _table(
            [
                ("Market value", metrics.total_value),
                ("Cost basis", metrics.total_cost),
                ("Unrealised P&L", metrics.unrealised_pnl),
                ("Return on cost", _percent(metrics.unrealised_pnl_pct)),
                ("Positions", metrics.position_count),
                (
                    "Valued at cost",
                    metrics.position_count - metrics.priced_positions,
                ),
            ]
        ),
        _heading("Holdings"),
        _holdings_table(positions, metrics.weights),
        _heading("Concentration"),
        _table(
            [
                ("Reading", metrics.concentration_reading),
                ("Diversification score", f"{metrics.diversification_score:.1f} / 100"),
                ("Concentration index (HHI)", f"{metrics.concentration_hhi:.4f}"),
                (
                    "Largest position",
                    f"{metrics.largest_position[0]} at {metrics.largest_position[1]:.1%}"
                    if metrics.largest_position
                    else None,
                ),
            ]
        ),
        _heading("Historical risk"),
        _table(
            [
                ("Observations", risk.observations),
                ("Annualised volatility", _percent(risk.annualised_volatility, 1)),
                ("Maximum drawdown", _percent(risk.max_drawdown, 1)),
                ("Current drawdown", _percent(risk.current_drawdown, 1)),
                ("Daily VaR (95%)", _percent(risk.var_95)),
                ("Expected shortfall (95%)", _percent(risk.expected_shortfall_95)),
            ]
        ),
    ]

    if risk.unavailable:
        # A missing figure must read as "not enough data", never as "no risk".
        parts.append(_heading("Figures not available", 3))
        parts.append(_bullets([f"{k}: {v}" for k, v in risk.unavailable.items()]))

    parts.append(
        "\n_All risk figures above are historical: they describe observed behaviour "
        "over the window measured, not a forecast._\n"
    )

    if stored is not None and stored.narrative:
        parts.append(_heading("Analyst reading"))
        parts.append(f"{stored.narrative}\n")

    parts.append(f"\n---\n\n_{REPORT_DISCLAIMER}_\n")

    return Report(
        title=f"Portfolio report — {portfolio.name}",
        generated_at=generated_at,
        markdown="\n".join(parts),
        payload={
            "portfolio": portfolio.name,
            "generated_at": generated_at.isoformat(),
            "metrics": metrics.as_dict(),
            "risk": risk.as_dict(),
            "narrative": stored.narrative if stored else None,
            "disclaimer": REPORT_DISCLAIMER,
        },
    )


def _holdings_table(positions, weights: dict[str, float]) -> str:
    lines = [
        "| Ticker | Sector | Quantity | Avg price | Last price | Value | Weight |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for p in sorted(positions, key=lambda x: weights.get(x.ticker, 0.0), reverse=True):
        last = "at cost" if p.last_price is None else str(p.last_price)
        lines.append(
            f"| {p.ticker} | {p.sector or 'unclassified'} | {p.quantity} | "
            f"{p.average_price} | {last} | {p.market_value} | "
            f"{weights.get(p.ticker, 0.0):.1%} |"
        )
    return "\n".join(lines) + "\n"


def latest_recommendation(session: Session, asset: Asset) -> Recommendation | None:
    return session.scalar(
        select(Recommendation)
        .join(AnalysisResult, AnalysisResult.id == Recommendation.analysis_result_id)
        .where(AnalysisResult.asset_id == asset.id)
        .order_by(Recommendation.created_at.desc())
    )


def engine_for(session: Session) -> PortfolioIntelligenceEngine:
    """Kept for callers that want fresh metrics rather than the stored report."""
    from aidss.llm.gateway import LLMGateway
    from aidss.llm.router import ModelRouter

    return PortfolioIntelligenceEngine(session, LLMGateway(ModelRouter([])))
