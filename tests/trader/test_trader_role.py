"""T1-08 / ADR-028: the `trader` role exists in the analysis platform and carries nothing extra."""

from __future__ import annotations

from aidss.db.models.user import UserRole
from aidss.security.rbac import permissions_for


def test_trader_role_exists_and_equals_a_viewer() -> None:
    assert UserRole("trader") is UserRole.TRADER
    assert permissions_for(UserRole.TRADER) == permissions_for(UserRole.VIEWER)


def test_no_trading_permission_is_defined_in_the_analysis_platform() -> None:
    every = {p for r in UserRole for p in permissions_for(r)}
    assert not [p for p in every if p.startswith("trade:")]
