"""Store the KORO spot-adapted OBV + EMA-ATR pullback strategy definition.

    docker exec -i stocks-trader-1 python - < deploy/trader/add_koro_strategy.py

Parameters come directly from the spot-applicable parts of KORO / Math Atlas (02/09 & 03/09):
- obv_reg_period = 48
- ema_period = 21
- max_extension_atr = 0.5
- autocorr_window = 180 (lag-1 autocorrelation > 0)
- vr_horizon = 6 (Variance Ratio VR(6) > 1)
- atr_period = 14, atr_stop_multiple = 2.5, cooldown_s = 14400 (one 4H candle)
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.runtime.settings_store import StrategyDef, get_strategy_def, set_strategy_def
from aidss_trader.strategy.kinds import build_strategy

SID = "koro_obv_pullback"
LABEL = "KORO OBV + EMA21 pullback (spot)"
PARAMS = {
    "obv_reg_period": "48",
    "ema_period": "21",
    "max_extension_atr": "0.5",
    "autocorr_window": "180",
    "vr_horizon": "6",
    "atr_period": "14",
    "atr_stop_multiple": "2.5",
    "cooldown_s": "14400",
}

engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
with sessionmaker(engine, expire_on_commit=False)() as session:
    version = build_strategy(SID, PARAMS).version_id()
    if get_strategy_def(session, SID) is not None:
        print(f"{SID}: exists, left alone")
    else:
        set_strategy_def(
            session, StrategyDef(SID, SID, LABEL, PARAMS), by="script:add_koro_strategy"
        )
        print(f"{SID}: created, version {version}")
    session.commit()
