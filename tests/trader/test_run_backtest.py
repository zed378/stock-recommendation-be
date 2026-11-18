"""The backtest runner (deploy/trader/run_backtest.py): read only by default, honest, bounded."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from aidss_trader.db.models import AuditLog, BacktestRunRow
from tests.trader.test_runtime_wiring import World, warm

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "trader" / "run_backtest.py"


def load():
    spec = importlib.util.spec_from_file_location("run_backtest", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_backtest"] = module  # a dataclass in the script resolves its module by name
    spec.loader.exec_module(module)
    return module


def stored_world() -> World:
    w = World("PAPER")
    warm(w, 3)  # the runtime stores candles and pair rules for the allowlisted pair
    return w


def test_default_run_prints_and_stores_nothing() -> None:
    module = load()
    w = stored_world()
    said: list[str] = []
    with w.factory() as s:
        lines = module.run(s, out=said.append)
        assert s.scalar(select(func.count()).select_from(BacktestRunRow)) == 0
    assert lines and lines[0].pair == "BTCIDR"
    assert any("nothing was stored" in x for x in said)


def test_record_writes_one_labelled_row_per_pair_and_audits_it() -> None:
    module = load()
    w = stored_world()
    with w.factory() as s:
        before = s.scalar(select(func.count()).select_from(AuditLog))
        lines = module.run(s, record=True, out=lambda _x: None)
        rows = list(s.scalars(select(BacktestRunRow)))
        assert len(rows) == len(lines) == 1
        assert rows[0].origin == "BACKTEST" and rows[0].pair == "BTCIDR"
        assert rows[0].ran_by.startswith("script:run_backtest")
        assert s.scalar(select(func.count()).select_from(AuditLog)) == before + 1


def test_it_refuses_to_guess_when_the_owners_numbers_are_missing() -> None:
    module = load()
    w = World("PAPER", configured=False)  # no strategy parameters, no paper numbers
    with w.factory() as s, pytest.raises(SystemExit):
        module.run(s, out=lambda _x: None)


def test_the_script_never_edits_settings_or_calls_the_exchange() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for banned in ("set_allowlist", "set_strategy_params", "save_risk_limits", "create_order",
                   "get_account", "KillSwitch", "requests", "httpx"):
        assert banned not in text, banned
