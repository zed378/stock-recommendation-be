"""Permanent guards for the boundary the whole design rests on (ADR-001, ADR-013, ADR-025).

Each guard first asserts that it is looking at something, so a wrong path cannot
turn it into a test that passes on an empty tree (the existing architecture test
does the same).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlalchemy import Numeric

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base, Money

ROOT = Path(__file__).resolve().parents[2]
AIDSS = ROOT / "src" / "aidss"
TRADER = ROOT / "src" / "aidss_trader"


def _py(path: Path) -> list[Path]:
    return sorted(path.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_guard_is_looking_at_real_trees() -> None:
    assert len(_py(AIDSS)) > 20 and len(_py(TRADER)) >= 10


def test_aidss_never_imports_the_trader() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in _py(AIDSS)
        if any(n == "aidss_trader" or n.startswith("aidss_trader.") for n in _imports(p))
    ]
    assert not offenders, f"aidss must not import aidss_trader: {offenders}"


def test_the_trader_never_imports_aidss() -> None:
    # `aidss_trader` shares a prefix with `aidss`, so compare whole module names.
    offenders = [
        str(p.relative_to(ROOT))
        for p in _py(TRADER)
        if any(n == "aidss" or n.startswith("aidss.") for n in _imports(p))
    ]
    assert not offenders, f"the Trader must not import aidss: {offenders}"


def test_the_trader_tree_is_not_under_aidss() -> None:
    """The analysis architecture test scans src/aidss; trading code must live outside it."""
    assert not (AIDSS / "trading").exists() and not (AIDSS / "trader").exists()


_WITHDRAWAL = re.compile(
    r"\b(withdraw_coin|withdraw_idr|withdraw_fiat|apply_withdraw|create_withdrawal|"
    r"deposit_address|list_deposit_address)\b|capital/withdraw|fiat/withdraw|capital/deposit",
    re.IGNORECASE,
)


def test_no_withdrawal_or_fund_movement_code_exists() -> None:
    hits = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _py(TRADER)
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _WITHDRAWAL.search(line)
    ]
    assert not hits, f"withdrawal / fund-movement code is forbidden (ADR-013): {hits}"


def test_the_withdrawal_guard_can_fail() -> None:
    assert _WITHDRAWAL.search("def withdraw_coin(self):")
    assert _WITHDRAWAL.search('"/api/v2/capital/withdraw/apply"')
    assert not _WITHDRAWAL.search("canWithdraw")  # reading the permission flag is required (FR-T04)


def test_every_table_is_in_the_trading_schema_and_no_money_column_is_a_float() -> None:
    tables = Base.metadata.tables.values()
    assert tables
    for table in tables:
        assert table.schema == SCHEMA
        for column in table.columns:
            kind = column.type
            assert type(kind).__name__ not in {"Float", "REAL", "DOUBLE", "DOUBLE_PRECISION"}, (
                f"{table.name}.{column.name} is a float type"
            )
            if isinstance(kind, Numeric):
                assert (kind.precision, kind.scale) == (Money.precision, Money.scale)


def test_no_order_or_broker_tables_appear_in_public_by_name() -> None:
    from aidss.db.base import Base as AidssBase

    forbidden = {"orders", "executions", "brokers", "trades"}
    assert not (set(AidssBase.metadata.tables) & forbidden)
