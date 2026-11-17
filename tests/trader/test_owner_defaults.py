"""The starter owner-numbers profile must stay loadable and self-consistent.

The profile is a proposal for the owner to edit (`deploy/trader/owner-defaults.starter.json`); this
guards against it drifting from what the Trader accepts (a renamed limit, a tightened range) and
checks that the checker itself still catches the mistakes it exists for.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = sorted((ROOT / "deploy" / "trader").glob("owner-defaults.*.json"))
LARGE = ROOT / "deploy" / "trader" / "owner-defaults.rp1000000.json"
SMALL = ROOT / "deploy" / "trader" / "owner-defaults.rp50000.json"
CHECKER = ROOT / "deploy" / "trader" / "check_owner_defaults.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_owner_defaults", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(path: Path = LARGE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_starter_profile_is_proposed_and_has_no_problem() -> None:
    assert len(PROFILES) >= 2
    for path in PROFILES:
        profile = _profile(path)
        assert profile["status"] == "proposed", path.name
        assert _checker().problems(profile) == [], path.name


def test_a_small_account_below_the_exchange_minimum_is_reported() -> None:
    """At Rp 50,000 a 0.5% risk sizes an entry at about Rp 5,000, under any realistic minimum order:
    every entry would be refused. The profile must say so rather than look fine."""
    profile = copy.deepcopy(_profile(SMALL))
    profile["limits"]["risk_per_trade_pct"] = "0.5"
    assert any(p.startswith("MINIMUM") for p in _checker().problems(profile))


def test_the_profile_sets_every_required_limit_and_nothing_unknown() -> None:
    from aidss_trader.config.limits import REQUIRED_RISK_FIELDS

    for path in PROFILES:
        limits = _profile(path)["limits"]
        missing = [
            n for n in REQUIRED_RISK_FIELDS if n != "daily_loss_day_boundary" and n not in limits
        ]
        assert missing == [], path.name


def test_a_missing_limit_is_reported_not_defaulted() -> None:
    profile = copy.deepcopy(_profile())
    profile["limits"]["max_daily_loss_idr"] = None
    assert any("max_daily_loss_idr is unset" in p for p in _checker().problems(profile))


def test_the_checker_catches_each_broken_relationship() -> None:
    check = _checker().problems
    cases = {
        "A2 vs A1": ("limits", "max_daily_loss_idr", "1000"),
        "A8 vs A6": ("limits", "max_order_idr", "900000"),
        "A6 vs A7": ("limits", "max_exposure_per_pair_pct", "60"),
        "C1 vs A10": ("limits", "freshness_limit_s", 20),
        "H3": ("promotion_thresholds", "max_paper_drawdown_pct", "20"),
        "I1": ("promotion_thresholds", "max_live_capital_idr", "5000000"),
    }
    for label, (section, key, value) in cases.items():
        profile = copy.deepcopy(_profile())
        profile[section][key] = value
        assert any(label in p for p in check(profile)), f"{label} not caught: {check(profile)}"


def test_a_value_the_api_would_refuse_is_refused_here() -> None:
    profile = copy.deepcopy(_profile())
    profile["limits"]["risk_per_trade_pct"] = "150"
    assert any("risk_per_trade_pct" in p for p in _checker().problems(profile))
