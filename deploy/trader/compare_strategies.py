"""Run every strategy over the same stored candles, with the same costs and limits.

    docker exec -i stocks-trader-1 python - < deploy/trader/compare_strategies.py
    docker exec -i stocks-trader-1 python - --owner-costs --record \
        < deploy/trader/compare_strategies.py

Read only unless `--record` is given. The reference `ema_adx` runs with the parameters stored in
the Trader; the others run with the fixed sets in `strategy/catalog.py`, written down before any
result was seen. Nothing here is tuned, and nothing it prints changes what the Trader does.

`--owner-costs` replaces the stored cost model with the fee numbers the owner read from the
Indodax account screen on 2026-11-19 (maker 0.10, taker 0.20, tax 0.21 on sales, clearing 0.00555)
for this run only, so a comparison can use the right costs before the owner applies the profile.

Read the result with care:
* The sample is about 300 four-hour bars per pair (roughly 50 days), which is short.
* Five rules over the same candles is five tries. The best of five on a short sample is partly
  luck, so a leader here is a candidate for a longer test, not a winner.
* The "market move" line is how far the pairs themselves moved over the same bars. It is
  context for a rising or falling market, not a result that can be compared with a strategy's
  return, because a strategy risks a small slice of equity per trade.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from aidss_trader.backtest.runner import load_inputs, run_strategy
from aidss_trader.db.models import Candle
from aidss_trader.paper.executor import CostModel
from aidss_trader.runtime.settings_store import list_strategy_defs
from aidss_trader.strategy.catalog import proposed_strategies
from aidss_trader.strategy.kinds import build_strategy

ACTOR = "script:compare_strategies (owner requested)"
OWNER_COSTS = CostModel(Decimal("0.10"), Decimal("0.20"), Decimal("0.21"), Decimal("0.00555"))


def main(argv: list[str]) -> int:
    engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
    record = "--record" in argv
    with sessionmaker(engine, expire_on_commit=False)() as session:
        inputs = load_inputs(session)
        if "--owner-costs" in argv:
            inputs = replace(inputs, paper=replace(inputs.paper, costs=OWNER_COSTS))
        costs = inputs.paper.costs
        print(
            f"costs: maker {costs.maker_fee_pct} taker {costs.taker_fee_pct} "
            f"tax {costs.tax_pct} clearing {costs.clearing_pct}; "
            f"start equity {inputs.start_equity_idr} IDR; {len(inputs.pairs)} pairs"
        )

        strategies = {}
        for d in list_strategy_defs(session):
            strategies[d.id] = build_strategy(d.kind, d.params)
        for name, strategy in proposed_strategies().items():
            strategies.setdefault(name, strategy)

        print(f"{'strategy':<22}{'version':<34}{'sum %':>9}{'trades':>8}{'pairs w/ trades':>17}")
        for sid, strategy in strategies.items():
            res = run_strategy(session, strategy, inputs, strategy_id=sid, record=record, by=ACTOR)
            traded = sum(1 for p in res.pairs if p.trades)
            print(f"{sid:<22}{res.version:<34}{res.return_pct:>9.3f}{res.trades:>8}{traded:>17}")

        moves = []
        for pair in inputs.pairs:
            closes = session.scalars(
                select(Candle.close)
                .where(Candle.pair == pair, Candle.timeframe == "4H")
                .order_by(Candle.open_time)
            ).all()
            if len(closes) > 1 and closes[0] > 0:
                moves.append((closes[-1] / closes[0] - 1) * 100)
        if moves:
            print(
                f"market move over the same bars: mean {sum(moves) / len(moves):.2f}% across "
                f"{len(moves)} pairs (context only, not comparable with the sums above)"
            )
        print("RECORDED to backtest_run." if record else "nothing was stored (read only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
