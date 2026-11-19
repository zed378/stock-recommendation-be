"""Run a strategy's backtest over the candles the Trader has stored, with the owner's numbers.

Shared by the API (a button on a strategy's tab) and by `deploy/trader/run_backtest.py`. It reads
the stored 4H candles, the pair rules, the paper cost model and the risk limits, and calls the same
`run_backtest` the tests exercise. Nothing is tuned and nothing the Trader acts on is changed; with
`record=True` one `backtest_run` row per pair is written (origin BACKTEST, never mixed with paper
or live) together with an audit entry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.backtest.engine import BacktestConfig, record_backtest, run_backtest
from aidss_trader.config.limits import RiskLimits
from aidss_trader.config.store import load_risk_limits
from aidss_trader.connector.types import Candle as ApiCandle
from aidss_trader.db.models import Candle, PairRule
from aidss_trader.market_data.pairs import PairRules
from aidss_trader.paper.executor import PaperConfig
from aidss_trader.runtime.settings_store import get_allowlist, get_paper_settings
from aidss_trader.strategy.base import Strategy

TIMEFRAME = "4H"


class BacktestInputsMissing(Exception):
    """The owner's numbers needed to run a backtest are not set."""


@dataclass(frozen=True, slots=True)
class PairResult:
    pair: str
    candles: int
    trades: int
    wins: int
    return_pct: Decimal
    max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class StrategyResult:
    strategy_id: str
    version: str
    pairs: list[PairResult]
    skipped: list[str]
    recorded: bool

    @property
    def return_pct(self) -> Decimal:
        """The plain sum of the per-pair returns (see `backtest.evidence` for why that is only an
        approximation)."""
        return sum((p.return_pct for p in self.pairs), Decimal(0))

    @property
    def trades(self) -> int:
        return sum(p.trades for p in self.pairs)


@dataclass(frozen=True, slots=True)
class Inputs:
    paper: PaperConfig
    start_equity_idr: Decimal
    limits: RiskLimits
    pairs: list[str]


def load_inputs(session: Session, pairs: list[str] | None = None) -> Inputs:
    paper = get_paper_settings(session)
    limits = load_risk_limits(session)
    if paper is None or limits is None:
        raise BacktestInputsMissing(
            "the paper cost model and the risk limits must be set before a backtest can run"
        )
    chosen = pairs or list(get_allowlist(session).pairs)
    if not chosen:
        raise BacktestInputsMissing("no pairs: the allowlist names none")
    return Inputs(paper.config, paper.start_equity_idr, limits, sorted(chosen))


def _rules(row: PairRule) -> PairRules:
    return PairRules(
        pair=row.pair,
        ticker_id=row.ticker_id,
        quantity_increment=row.quantity_increment,
        price_increment=row.price_increment,
        min_base_idr=row.min_base_idr,
        min_traded_qty=row.min_traded_qty,
        maintenance=row.maintenance,
        suspended=row.suspended,
        blocked_reasons=tuple(row.blocked_reasons or ()),
    )


def run_strategy(
    session: Session,
    strategy: Strategy,
    inputs: Inputs,
    *,
    strategy_id: str,
    record: bool,
    by: str,
    progress: Callable[[str], None] | None = None,
) -> StrategyResult:
    """`strategy_id` is the owner's name for the strategy, not the rule's kind: two strategies of
    the same kind with different names keep separate evidence."""
    results: list[PairResult] = []
    skipped: list[str] = []
    for pair in inputs.pairs:
        if progress is not None:
            progress(pair)
        rows = session.scalars(
            select(Candle)
            .where(Candle.pair == pair, Candle.timeframe == TIMEFRAME)
            .order_by(Candle.open_time)
        ).all()
        rule_row = session.get(PairRule, pair)
        if len(rows) <= strategy.min_history() or rule_row is None:
            skipped.append(pair)
            continue
        candles = [ApiCandle(r.open_time, r.open, r.high, r.low, r.close, r.volume) for r in rows]
        config = BacktestConfig(
            strategy=strategy,
            limits=inputs.limits,
            rules=_rules(rule_row),
            paper=inputs.paper,
            start_equity_idr=inputs.start_equity_idr,
            pair=pair,
        )
        result = run_backtest(candles, config)
        m = result.metrics
        results.append(
            PairResult(
                pair,
                result.candles_used,
                int(m["trades"]),
                int(m["wins"]),
                Decimal(str(m["total_return_pct"])),
                Decimal(str(m["max_drawdown_pct"])),
            )
        )
        if record:
            record_backtest(
                session,
                result,
                config,
                strategy_id=strategy_id,
                timeframe=TIMEFRAME,
                by=by,
            )
    return StrategyResult(
        strategy_id=strategy_id,
        version=strategy.version_id(),
        pairs=results,
        skipped=skipped,
        recorded=record,
    )
