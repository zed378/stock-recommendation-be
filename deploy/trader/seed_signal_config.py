"""Seed the crypto signal worker's settings once, from the numbers it was already running with.

    docker exec -i stocks-trader-1 python - < deploy/trader/seed_signal_config.py

Only writes when no settings row exists, so it never overwrites what the owner set on the screen.
The values are the placeholders the worker was started with (not the owner's choices, apart from
horizons 14d and 30d, the 0.8 threshold and Top N 5), mode SHADOW, enabled. Change them on the
operator screen.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.signals_config import get_settings_row, parse_settings, set_signal_settings

SEED = {
    "enabled": True,
    "mode": "SHADOW",
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "top_n": 5,
    "min_quote_volume_usdt": "50000000",
    "horizons": ["14d", "30d"],
    "min_score_ratio": "0.8",
    "atr_stop_multiple": "2.5",
    "tp_r": ["1.5", "2.5", "4"],
    "ai_min_score": 70,
    "ai_max_calls": 10,
}

engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
with sessionmaker(engine, expire_on_commit=False)() as session:
    if get_settings_row(session) is not None:
        print("settings already exist; left alone")
    else:
        set_signal_settings(session, parse_settings(SEED), by="script:seed_signal_config")
        session.commit()
        print("seeded:", SEED)
