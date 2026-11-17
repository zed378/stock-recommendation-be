"""Check a filled owner-numbers profile before anyone types it into the Trader.

    python deploy/trader/check_owner_defaults.py [profile.json]

Read-only: it opens the file, builds the Trader's own value objects from it (so a value the
Trader would refuse is refused here too), and checks the relationships in
docs/01-PRODUCT-REQUIREMENTS/08-OWNER-NUMBERS-WORKSHEET.md ("Relationships That Must Hold").
It talks to no database, no API and no exchange. Exit status 0 means no problem was found, not
that the numbers are good: they are still the owner's call.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from aidss_trader.api.app import limit_problem
from aidss_trader.config.limits import REQUIRED_RISK_FIELDS, RiskLimits, unset_risk_fields
from aidss_trader.paper import CostModel, PaperConfig
from aidss_trader.promotion.gates import Thresholds
from aidss_trader.runtime.settings_store import MAX_HISTORY_BARS
from aidss_trader.strategy.ema_adx import EmaAdxParams, EmaAdxStrategy

DEFAULT_PROFILE = Path(__file__).with_name("owner-defaults.rp50000.json")

# Decided values the relationships depend on (worksheet sections C and D; ADR-041 to ADR-043).
PRICE_POLL_S = 10
WATCHDOG_S = 30
APPROVAL_EXPIRY_S = 3600
CANDLE_SECONDS = {"4H": 4 * 3600, "1D": 24 * 3600}

INT_LIMITS = {
    "max_consecutive_losses",
    "max_open_positions",
    "freshness_limit_s",
    "cooldown_s",
    "order_rate_limit",
}


def _dec(value: Any, label: str, found: list[str]) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        found.append(f"{label}: {value!r} is not a number")
        return Decimal(0)


def problems(profile: dict[str, Any]) -> list[str]:
    found: list[str] = []
    basis = profile.get("basis", {})
    equity = _dec(basis.get("equity_idr"), "basis.equity_idr", found)
    if equity <= 0:
        found.append("basis.equity_idr must be above 0")
        return found
    timeframe = basis.get("timeframe")
    if timeframe not in CANDLE_SECONDS:
        found.append("basis.timeframe must be 4H or 1D")

    # --- limits: the API's own range checks, then the Trader's "is anything unset" rule.
    raw = profile.get("limits", {})
    parsed: dict[str, Any] = {}
    for name, value in raw.items():
        if name not in REQUIRED_RISK_FIELDS and name not in (
            "trading_window",
            "daily_loss_day_boundary",
        ):
            found.append(f"limits.{name}: unknown limit")
            continue
        if value is None or name in ("trading_window", "daily_loss_day_boundary"):
            parsed[name] = value
        elif name in INT_LIMITS:
            parsed[name] = int(value)
        else:
            parsed[name] = _dec(value, f"limits.{name}", found)
        if (why := limit_problem(name, parsed[name])) is not None:
            found.append(f"limits.{name}: {why}")
    limits = RiskLimits(**parsed)
    for name in unset_risk_fields(limits):
        found.append(f"limits.{name} is unset: the strategy stays disabled")
    if found:
        return found

    a = limits
    assert a.risk_per_trade_pct is not None and a.max_daily_loss_idr is not None
    assert a.max_drawdown_pct is not None and a.max_open_positions is not None
    assert a.max_exposure_per_pair_pct is not None and a.max_total_exposure_pct is not None
    assert a.max_order_idr is not None and a.freshness_limit_s is not None
    one_stop = equity * a.risk_per_trade_pct / 100
    pair_cap = equity * a.max_exposure_per_pair_pct / 100
    if a.max_daily_loss_idr < one_stop:
        found.append(
            f"A2 vs A1: the daily loss limit ({a.max_daily_loss_idr}) is below one full stop "
            f"({one_stop}); an ordinary stopped trade would trip it"
        )
    if a.max_order_idr > pair_cap:
        found.append(
            f"A8 vs A6: max_order_idr {a.max_order_idr} exceeds the per-pair cap {pair_cap}"
        )
    if a.max_exposure_per_pair_pct > a.max_total_exposure_pct:
        found.append("A6 vs A7: per-pair exposure exceeds total exposure")
    if a.max_open_positions * a.max_exposure_per_pair_pct > a.max_total_exposure_pct:
        found.append(
            "A5 vs A6/A7: open positions x per-pair cap "
            f"({a.max_open_positions * a.max_exposure_per_pair_pct}%) exceeds the total cap "
            f"({a.max_total_exposure_pct}%); the total cap will bind first"
        )
    if a.max_daily_loss_idr / equity * 100 >= a.max_drawdown_pct:
        found.append(
            "A3 vs A2: the daily loss is at or above the drawdown limit, which would trip first"
        )
    if a.freshness_limit_s < 3 * PRICE_POLL_S:
        found.append(
            f"C1 vs A10: freshness {a.freshness_limit_s}s is under 3 x the {PRICE_POLL_S}s poll"
        )
    if PRICE_POLL_S * 2 > WATCHDOG_S:
        found.append("C1 vs C4: the watchdog leaves no margin over the price poll")
    # The sizing rule (intents/builder.py) takes the smallest of the risk-based size and the caps,
    # then refuses an order below the pair's minimum instead of rounding it up. On a small account
    # the minimum, not the preference, decides whether any entry can happen at all.
    min_order = _dec(basis.get("min_order_idr"), "basis.min_order_idr", found)
    stop_pct = _dec(basis.get("assumed_stop_pct"), "basis.assumed_stop_pct", found)
    if min_order > 0 and stop_pct > 0:
        total_cap = equity * a.max_total_exposure_pct / 100
        implied = min(one_stop / (stop_pct / 100), pair_cap, total_cap, a.max_order_idr)
        if implied < min_order:
            found.append(
                f"MINIMUM: a {stop_pct}% stop sizes an entry at about {implied:.0f} IDR, below the "
                f"{min_order} IDR minimum order, so every entry would be refused. Raise "
                "risk_per_trade_pct or the exposure caps, or use more capital"
            )
    if timeframe in CANDLE_SECONDS and APPROVAL_EXPIRY_S >= CANDLE_SECONDS[timeframe]:
        found.append("D5 vs E4: the approval expiry is not shorter than the candle period")

    # --- strategy parameters
    sp = profile.get("strategy_params", {})
    try:
        params = EmaAdxParams(
            ema_fast=int(sp["ema_fast"]),
            ema_slow=int(sp["ema_slow"]),
            adx_period=int(sp["adx_period"]),
            adx_threshold=Decimal(str(sp["adx_threshold"])),
            atr_period=int(sp["atr_period"]),
            atr_stop_multiple=Decimal(str(sp["atr_stop_multiple"])),
            cooldown_s=int(sp["cooldown_s"]),
        )
    except (KeyError, ValueError, InvalidOperation) as exc:
        found.append(f"strategy_params: {exc}")
    else:
        needed = EmaAdxStrategy(params).min_history()
        if needed > MAX_HISTORY_BARS:
            found.append(f"strategy_params need {needed} bars but only {MAX_HISTORY_BARS} are kept")

    # --- paper cost model
    pp = profile.get("paper", {})
    try:
        PaperConfig(
            slippage_pct=Decimal(str(pp["slippage_pct"])),
            partial_fill_fraction=Decimal(str(pp["partial_fill_fraction"])),
            costs=CostModel(
                Decimal(str(pp["maker_fee_pct"])),
                Decimal(str(pp["taker_fee_pct"])),
                Decimal(str(pp["tax_pct"])),
                Decimal(str(pp["clearing_pct"])),
            ),
        )
        if Decimal(str(pp["start_equity_idr"])) != equity:
            found.append("paper.start_equity_idr differs from basis.equity_idr")
    except (KeyError, ValueError, InvalidOperation) as exc:
        found.append(f"paper: {exc}")

    # --- allowlist
    al = profile.get("allowlist", {})
    if not al.get("pairs"):
        found.append("allowlist.pairs is empty")
    for key in ("min_quote_volume_24h_idr", "max_spread_pct"):
        if _dec(al.get(key), f"allowlist.{key}", found) <= 0:
            found.append(f"allowlist.{key} must be above 0")

    # --- promotion thresholds (H): set before any evidence exists
    pt = profile.get("promotion_thresholds", {})
    th = Thresholds(
        min_paper_trades=pt.get("min_paper_trades"),
        max_paper_drawdown_pct=_dec(
            pt.get("max_paper_drawdown_pct"), "max_paper_drawdown_pct", found
        ),
        backtest_min_return_pct=_dec(
            pt.get("backtest_min_return_pct"), "backtest_min_return_pct", found
        ),
        max_live_capital_idr=_dec(pt.get("max_live_capital_idr"), "max_live_capital_idr", found),
        max_slippage_pct=_dec(pt.get("max_slippage_pct"), "max_slippage_pct", found),
    )
    if not isinstance(th.min_paper_trades, int) or th.min_paper_trades < 1:
        found.append("promotion_thresholds.min_paper_trades must be a whole number of at least 1")
    if th.max_paper_drawdown_pct is not None and th.max_paper_drawdown_pct > a.max_drawdown_pct:
        found.append("H3: the paper drawdown gate is looser than the live drawdown limit (A3)")
    if th.max_live_capital_idr is not None and th.max_live_capital_idr > equity:
        found.append("I1: the live capital gate exceeds the equity the profile is built for")
    return found


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PROFILE
    profile = json.loads(path.read_text(encoding="utf-8"))
    found = problems(profile)
    for line in found:
        print("PROBLEM:", line)
    basis = profile.get("basis", {})
    if basis.get("min_order_note"):
        print("NOTE:", basis["min_order_note"])
    if not found:
        print(f"{path.name}: no problem found (status: {profile.get('status', '?')})")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
