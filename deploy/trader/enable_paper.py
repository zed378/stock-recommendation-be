"""Switch strategies on in the paper loop, the same steps as `PUT /strategy-defs/{id}/paper`.

    docker exec -i stocks-trader-1 python - d2_di_confirm d7_di_atr < deploy/trader/enable_paper.py

Registers the strategy's current version as PAPER and sets its enabled flag. It refuses the
reference strategy, an id with no definition, numbers that do not build, and more than the cap.
Paper only: nothing here can create a live order.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aidss_trader.promotion import Promotion
from aidss_trader.runtime.settings_store import (
    MAX_ENABLED_STRATEGIES,
    enabled_strategy_ids,
    get_strategy_def,
    set_strategy_enabled,
)
from aidss_trader.strategy.kinds import ParameterError, build_strategy

ids = [a for a in sys.argv[1:] if not a.startswith("-")]
if not ids:
    raise SystemExit("name at least one strategy id")
engine = create_engine(os.environ["AIDSS_TRADER_DATABASE_URL"])
with sessionmaker(engine, expire_on_commit=False)() as session:
    for sid in ids:
        if sid == "ema_adx":
            raise SystemExit("ema_adx follows its own mode, not this switch")
        d = get_strategy_def(session, sid)
        if d is None:
            raise SystemExit(f"{sid}: no such strategy")
        try:
            version = build_strategy(d.kind, d.params).version_id()
        except ParameterError as exc:
            raise SystemExit(f"{sid}: {exc}") from None
        others = [i for i in enabled_strategy_ids(session) if i != sid]
        if len(others) >= MAX_ENABLED_STRATEGIES:
            raise SystemExit(f"at most {MAX_ENABLED_STRATEGIES} strategies can run in paper")
        Promotion(session).register(sid, version)
        set_strategy_enabled(session, sid, True, by="script:enable_paper (owner requested)")
        session.commit()
        print(f"{sid}: enabled in paper, version {version}")
    print("enabled now:", enabled_strategy_ids(session))
