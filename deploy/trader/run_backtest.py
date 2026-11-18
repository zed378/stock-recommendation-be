"""Run the Trader's own backtest over the candles it has stored, with the owner's numbers.

    docker exec -i stocks-trader-1 python - < deploy/trader/run_backtest.py            # read only
    docker exec -i stocks-trader-1 python - --record < deploy/trader/run_backtest.py   # and store

(`python - --record` hands the flag to the script read from stdin.) Run inside the Trader
container, where the database URL and the package already are. What it does and does not do:

* It changes nothing the Trader acts on. It reads the stored 4H candles, the stored strategy
  parameters, the paper cost model, the risk limits and the pair rules, and calls the same
  `run_backtest` the tests exercise. Nothing is tuned: the parameters are the ones in force.
* Without `--record` it only prints. With it, one row per pair is written to `backtest_run`
  (origin BACKTEST, never mixed with live or paper) and one audit entry each.
* Every pair is reported, wins and losses alike. The promotion gates read a number the owner
  supplies, so this is evidence to read, not a switch.
* It uses the pairs the owner named in the allowlist; markets that only ALL selects are not
  included, because they have no stored candles worth testing yet.

Limits to keep in mind when reading the result: the stored history is about 300 four-hour bars
(roughly 50 days), a short sample; costs and slippage are the owner's paper numbers; the engine
prices fills from candles, not from an order book (see the engine's docstring).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.backtest import BacktestConfig, record_backtest, run_backtest
from aidss_trader.config.store import load_risk_limits
from aidss_trader.connector.types import Candle as ApiCandle
from aidss_trader.db.models import Candle, PairRule
from aidss_trader.market_data.pairs import PairRules
from aidss_trader.runtime.settings_store import (
    get_allowlist,
    get_paper_settings,
    load_strategy,
)

TIMEFRAME = "4H"
ACTOR = "script:run_backtest (owner requested)"


@dataclass(frozen=True, slots=True)
class Line:
    pair: str
    candles: int
    trades: int
    wins: int
    return_pct: Decimal
    max_drawdown_pct: Decimal
    profit_factor: Decimal


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


def run(
    session: Session,
    *,
    pairs: list[str] | None = None,
    record: bool = False,
    out=print,
) -> list[Line]:
    strategy = load_strategy(session)
    paper = get_paper_settings(session)
    limits = load_risk_limits(session)
    if strategy is None or paper is None or limits is None:
        raise SystemExit(
            "need stored strategy parameters, the paper cost model and the risk limits first"
        )
    chosen = pairs or list(get_allowlist(session).pairs)
    if not chosen:
        raise SystemExit("no pairs: the allowlist names none and none were given")

    lines: list[Line] = []
    for pair in sorted(chosen):
        rows = session.scalars(
            select(Candle)
            .where(Candle.pair == pair, Candle.timeframe == TIMEFRAME)
            .order_by(Candle.open_time)
        ).all()
        rule_row = session.get(PairRule, pair)
        if len(rows) <= strategy.min_history() or rule_row is None:
            out(f"{pair}: skipped (not enough stored candles or no pair rules)")
            continue
        candles = [ApiCandle(r.open_time, r.open, r.high, r.low, r.close, r.volume) for r in rows]
        config = BacktestConfig(
            strategy=strategy,
            limits=limits,
            rules=_rules(rule_row),
            paper=paper.config,
            start_equity_idr=paper.start_equity_idr,
            pair=pair,
        )
        result = run_backtest(candles, config)
        m = result.metrics
        lines.append(
            Line(
                pair,
                result.candles_used,
                int(m["trades"]),
                int(m["wins"]),
                Decimal(str(m["total_return_pct"])),
                Decimal(str(m["max_drawdown_pct"])),
                Decimal(str(m["profit_factor"])),
            )
        )
        if record:
            record_backtest(session, result, config, timeframe=TIMEFRAME, by=ACTOR)

    out(f"strategy {strategy.version_id()}, start equity {paper.start_equity_idr} IDR")
    out(f"{'pair':<12}{'candles':>8}{'trades':>8}{'wins':>6}{'return %':>11}{'max dd %':>10}")
    for line in lines:
        out(
            f"{line.pair:<12}{line.candles:>8}{line.trades:>8}{line.wins:>6}"
            f"{line.return_pct:>11.3f}{line.max_drawdown_pct:>10.3f}"
        )
    traded = [x for x in lines if x.trades]
    out(
        f"{len(lines)} pairs run, {len(traded)} produced trades, "
        f"{sum(x.trades for x in lines)} trades in total; "
        + ("RECORDED to backtest_run." if record else "nothing was stored (read only).")
    )
    return lines


def main(argv: list[str]) -> int:
    engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
    with sessionmaker(engine, expire_on_commit=False)() as session:
        run(session, record="--record" in argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
