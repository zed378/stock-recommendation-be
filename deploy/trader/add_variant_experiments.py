"""Store the one-change variants D1 to D5, and the combined D6 and D7, as definitions (ADR-063).

    docker exec -i stocks-trader-1 python - < deploy/trader/add_variant_experiments.py

Each variant takes its parent's **stored** numbers unchanged (D1 to D5: the reference; D6 and D7:
D2) and adds one extra number, so a backtest difference comes from that one change. The extra
numbers are the builder's suggested starting points, not tuned values. An id that already
exists is left alone.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.runtime.settings_store import StrategyDef, get_strategy_def, set_strategy_def
from aidss_trader.strategy.kinds import build_strategy

# (id, label, kind, extra numbers, parent id or None for the reference)
EXPERIMENTS = [
    ("d1_adx_rising", "D1 ADX naik", "ema_adx_rising", {"rise_bars": "3"}),
    ("d2_di_confirm", "D2 Konfirmasi DI", "ema_adx_di", {"di_margin": "0"}),
    ("d3_atr_filter", "D3 Filter volatilitas", "ema_adx_atr_filter", {"min_atr_pct": "0.5"}),
    ("d4_atr_trail", "D4 Trailing stop", "ema_adx_trail", {"trail_atr_multiple": "3"}),
    ("d5_regime", "D5 Rezim pasar", "ema_adx_regime", {"er_period": "10", "er_min": "0.3"}),
    ("d6_di_rising", "D6 DI + ADX naik", "ema_adx_di_rising", {"rise_bars": "3"}, "d2_di_confirm"),
    (
        "d7_di_atr",
        "D7 DI + filter volatilitas",
        "ema_adx_di_atr_filter",
        {"min_atr_pct": "0.5"},
        "d2_di_confirm",
    ),
]

engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
with sessionmaker(engine, expire_on_commit=False)() as session:
    reference = get_strategy_def(session, "ema_adx")
    if reference is None:
        raise SystemExit("the reference strategy has no stored parameters")
    print("reference numbers:", reference.params)
    for sid, label, kind, extra, *rest in EXPERIMENTS:
        if get_strategy_def(session, sid) is not None:
            print(f"{sid}: exists, left alone")
            continue
        parent = get_strategy_def(session, rest[0]) if rest else reference
        if parent is None:
            print(f"{sid}: skipped, parent {rest[0]} is not defined")
            continue
        params = {**parent.params, **extra}
        version = build_strategy(kind, params).version_id()
        set_strategy_def(
            session, StrategyDef(sid, kind, label, params), by="script:add_variant_experiments"
        )
        print(f"{sid}: created ({kind}), version {version}")
    session.commit()
