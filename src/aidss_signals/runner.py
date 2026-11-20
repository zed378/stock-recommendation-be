"""The worker's loop in database mode (ADR-066): read the owner's settings, decide whether a pass is
due, run it, and keep what it found.

A pass is due when the daily schedule says so (once after each 00:05 UTC close) or when the owner
asked for one on the screen. Disabled or incomplete settings keep the worker idle, and the settings
are re-read every poll, so a change on the screen takes effect without restarting anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from aidss_signals.ai_review import Reviewer
from aidss_signals.config import ConfigError, SignalsConfig, config_from_settings
from aidss_signals.h4_pass import H4Report, h4_slot, run_h4_pass
from aidss_signals.market import MarketData
from aidss_signals.store import DbState, SignalStore
from aidss_signals.worker import PassReport, run_pass
from aidss_trader.signals_config import daily_unset_fields, unset_fields

SCHEDULE_OFFSET = timedelta(minutes=5)  # after the 00:00 UTC close, once the exchange settled it


def schedule_slot(now: datetime) -> datetime:
    """The most recent scheduled pass time at or before `now`."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0) + SCHEDULE_OFFSET
    return today if today <= now else today - timedelta(days=1)


@dataclass(slots=True)
class Due:
    kind: str  # SCHEDULED | MANUAL


def due_pass(store: SignalStore, now: datetime, requested_at: datetime | None) -> Due | None:
    last_any = store.last_scan_started()
    if requested_at is not None and (last_any is None or last_any < requested_at):
        return Due("MANUAL")
    last_sched = store.last_scan_started("SCHEDULED")
    if last_sched is None or last_sched < schedule_slot(now):
        return Due("SCHEDULED")
    return None


def poll_once(
    store: SignalStore,
    market_for: Callable[[SignalsConfig], MarketData],
    reviewer: Callable[[], Reviewer],
    publish: Callable[[dict[str, Any]], None],
    env: dict[str, str],
    now: datetime,
    log: Callable[[str, str], None] = lambda _l, _m: None,
    receiver_ready: bool = False,
) -> PassReport | None:
    """One look at the database: run a pass if one is due. Returns the report, or None if idle."""
    settings, requested_at = store.load_settings()
    if not settings.enabled:
        return None
    missing = daily_unset_fields(settings)
    if missing:
        log("WARN", "signals: idle, these settings are not set: " + ", ".join(missing))
        return None
    due = due_pass(store, now, requested_at)
    if due is None:
        return None
    try:
        cfg = config_from_settings(settings, env)
    except ConfigError as exc:
        log("ERROR", f"signals: not running ({exc})")
        return None
    mode = cfg.mode
    if mode == "PUBLISH" and not receiver_ready:
        # The owner asked for PUBLISH but there is nowhere to publish to. Do not pretend: scan in
        # SHADOW, which sends nothing, and say so.
        log(
            "WARN",
            "signals: PUBLISH requested but no receiver server is configured; running SHADOW",
        )
        cfg = replace(cfg, mode="SHADOW")
        mode = "SHADOW"
    scan_id = store.begin_scan(due.kind, mode)
    status = "DONE"
    try:
        report = run_pass(
            cfg,
            market_for(cfg),
            reviewer(),
            publish,
            now,
            DbState(store),
            lambda entry: store.save_candidate(scan_id, mode, entry),
            log,
        )
        if report.errors and not report.outcomes:
            status = "FAILED"
    except Exception as exc:  # noqa: BLE001 - a pass must leave a record even when it breaks
        store.finish_scan(
            scan_id,
            status="FAILED",
            universe=[],
            outcomes={},
            errors=[type(exc).__name__],
            ai_calls=0,
            signals=0,
        )
        log("ERROR", f"signals: pass failed ({type(exc).__name__})")
        return None
    store.finish_scan(
        scan_id,
        status=status,
        universe=report.universe,
        outcomes=report.outcomes,
        errors=report.errors,
        ai_calls=report.ai_calls,
        signals=len(report.signals),
    )
    return report


def due_h4(store: SignalStore, now: datetime, requested_at: datetime | None) -> Due | None:
    """Due after each 4H close, and whenever the owner asked and no 4-hour pass has run since."""
    last_any = store.last_scan_started(prefix="H4")
    if requested_at is not None and (last_any is None or last_any < requested_at):
        return Due("H4MANUAL")
    last_sched = store.last_scan_started(kind="H4")
    if last_sched is None or last_sched < h4_slot(now):
        return Due("H4")
    return None


def poll_h4(
    store: SignalStore,
    market_for: Callable[[SignalsConfig], MarketData],
    publish: Callable[[dict[str, Any]], None],
    env: dict[str, str],
    now: datetime,
    log: Callable[[str, str], None] = lambda _l, _m: None,
    receiver_ready: bool = False,
) -> H4Report | None:
    """One look at the database for the 4-hour signals: run a pass if one is due and the owner has
    switched them on with every number set."""
    settings, requested_at = store.load_settings()
    if not settings.enabled or not settings.h4.enabled:
        return None
    missing = unset_fields(settings)
    if missing:
        log("WARN", "signals 4h: idle, these settings are not set: " + ", ".join(missing))
        return None
    due = due_h4(store, now, requested_at)
    if due is None:
        return None
    try:
        cfg = config_from_settings(settings, env)
    except ConfigError as exc:
        log("ERROR", f"signals 4h: not running ({exc})")
        return None
    if cfg.mode == "PUBLISH" and not receiver_ready:
        log("WARN", "signals 4h: PUBLISH requested but no receiver server; running SHADOW")
        cfg = replace(cfg, mode="SHADOW")
    scan_id = store.begin_scan(due.kind, cfg.mode)
    try:
        report = run_h4_pass(cfg, store, market_for(cfg), scan_id, publish, now, log)
    except Exception as exc:  # noqa: BLE001 - a pass must leave a record even when it breaks
        store.finish_scan(
            scan_id,
            status="FAILED",
            universe=[],
            outcomes={},
            errors=[type(exc).__name__],
            ai_calls=0,
            signals=0,
        )
        log("ERROR", f"signals 4h: pass failed ({type(exc).__name__})")
        return None
    store.finish_scan(
        scan_id,
        status="FAILED" if report.errors and not report.outcomes else "DONE",
        universe=report.universe,
        outcomes=report.outcomes,
        errors=report.errors,
        ai_calls=0,
        signals=len(report.new_signals),
    )
    return report
