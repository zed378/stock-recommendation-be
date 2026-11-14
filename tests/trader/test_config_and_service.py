from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from aidss_trader.config import REQUIRED_RISK_FIELDS, RiskLimits, TraderSettings, unset_risk_fields
from aidss_trader.lease import LeaseHolder
from aidss_trader.service import TradingState, evaluate, heartbeat_age_s, write_heartbeat

_DECIDED = {"daily_loss_day_boundary"}  # ADR-034: the owner's recorded choice


def test_no_loss_limiting_setting_has_a_default() -> None:
    """The mechanism must not be able to become permissive by omission."""
    defaults = {
        f.name: f.default
        for f in fields(RiskLimits)
        if f.name not in _DECIDED and f.default is not None
    }
    assert defaults == {}, f"these limits have a default value: {defaults}"
    assert RiskLimits().daily_loss_day_boundary == "LOCAL"


def test_an_empty_or_missing_limit_set_is_fully_unset() -> None:
    assert unset_risk_fields(None) == list(REQUIRED_RISK_FIELDS)
    assert "daily_loss_day_boundary" not in unset_risk_fields(RiskLimits())
    assert "trading_window" not in REQUIRED_RISK_FIELDS  # optional by design


def test_setting_one_limit_leaves_the_rest_unset() -> None:
    limits = RiskLimits(max_order_idr=Decimal("1"))
    missing = unset_risk_fields(limits)
    assert "max_order_idr" not in missing and len(missing) == len(REQUIRED_RISK_FIELDS) - 2


def test_lease_heartbeat_must_be_shorter_than_ttl(monkeypatch) -> None:
    monkeypatch.setenv("AIDSS_TRADER_DATABASE_URL", "sqlite://")
    assert TraderSettings().lease_ttl_s == 15 and TraderSettings().lease_heartbeat_s == 5  # ADR-043
    with pytest.raises(ValidationError):
        TraderSettings(lease_ttl_s=5, lease_heartbeat_s=5)


def test_t1_trader_is_always_disabled_and_says_why(session, monkeypatch, key_file) -> None:
    monkeypatch.setenv("AIDSS_TRADER_DATABASE_URL", "sqlite://")
    settings = TraderSettings(master_key_file=key_file)
    status = evaluate(settings, session, LeaseHolder("a", 15))
    assert status.state is TradingState.DISABLED
    assert status.holds_lease is True
    assert any("risk limits are unset" in r for r in status.reasons)


def test_missing_master_key_is_reported_not_raised(session, monkeypatch) -> None:
    monkeypatch.setenv("AIDSS_TRADER_DATABASE_URL", "sqlite://")
    status = evaluate(TraderSettings(), session, LeaseHolder("a", 15))
    assert status.state is TradingState.DISABLED
    assert any("master key unavailable" in r for r in status.reasons)


def test_second_instance_is_told_it_does_not_hold_the_lease(session, monkeypatch, key_file) -> None:
    monkeypatch.setenv("AIDSS_TRADER_DATABASE_URL", "sqlite://")
    settings = TraderSettings(master_key_file=key_file)
    evaluate(settings, session, LeaseHolder("a", 15))
    second = evaluate(settings, session, LeaseHolder("b", 15))
    assert second.holds_lease is False
    assert any("another Trader instance" in r for r in second.reasons)


def test_heartbeat_age(tmp_path) -> None:
    path = tmp_path / "hb"
    assert heartbeat_age_s(path) is None
    now = datetime(2026, 11, 14, tzinfo=UTC)
    write_heartbeat(path, now)
    assert heartbeat_age_s(path, now + timedelta(seconds=7)) == 7
