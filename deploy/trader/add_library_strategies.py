"""Store the four library strategies as definitions, with the catalog's exact numbers.

    docker exec -i stocks-trader-1 python - < deploy/trader/add_library_strategies.py

Same effect as creating them one by one in the builder. The ids and numbers match
`strategy/catalog.py`, so the backtest results already stored under those versions show on the
new tabs. An id that already exists is left alone.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.runtime.settings_store import StrategyDef, get_strategy_def, set_strategy_def
from aidss_trader.strategy.kinds import build_strategy

COMMON = {"atr_period": "14", "atr_stop_multiple": "2.5", "cooldown_s": "14400"}
DEFS = [
    ("donchian_breakout", "Donchian breakout", {"entry_period": "20", "exit_period": "10"}),
    (
        "rsi_reversion",
        "RSI mean reversion",
        {"rsi_period": "14", "oversold": "30", "exit_level": "55"},
    ),
    ("bollinger_reversion", "Bollinger mean reversion", {"period": "20", "width": "2"}),
    (
        "macd_trend",
        "MACD + trend filter",
        {"fast": "12", "slow": "26", "signal": "9", "trend_period": "100"},
    ),
]

engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
with sessionmaker(engine, expire_on_commit=False)() as session:
    for sid, label, own in DEFS:
        params = {**own, **COMMON}
        version = build_strategy(sid, params).version_id()
        if get_strategy_def(session, sid) is not None:
            print(f"{sid}: exists, left alone")
            continue
        set_strategy_def(
            session, StrategyDef(sid, sid, label, params), by="script:add_library_strategies"
        )
        print(f"{sid}: created, version {version}")
    session.commit()
