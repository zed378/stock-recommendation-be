"""Reconciliation (ADR-022): the exchange is the truth, and a difference halts.

A difference is never silently corrected. It is recorded, the run is marked
`differences`, and trading is HALTed until the owner resolves it. The reconciler
only reads from the exchange; the only write it can cause is the HALT.

History reads are windowed to 7 days because the exchange caps the range.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.connector.client import IndodaxClient
from aidss_trader.connector.errors import ConnectorError
from aidss_trader.db.models import Fill, OrderRow, ReconciliationDifference, ReconciliationRun
from aidss_trader.killswitch import KillSwitch
from aidss_trader.orders.state import TERMINAL, OrderState

WINDOW = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(UTC)


def windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out, cursor = [], start
    while cursor < end:
        nxt = min(cursor + WINDOW, end)
        out.append((cursor, nxt))
        cursor = nxt
    return out


def reconcile(
    session: Session,
    client: IndodaxClient,
    pairs: list[str],
    *,
    lookback: timedelta = timedelta(days=1),
    now: Callable[[], datetime] = _now,
    killswitch: KillSwitch | None = None,
) -> ReconciliationRun:
    started = now()
    run = ReconciliationRun(started_at=started, result="failed", differences=0)
    session.add(run)
    session.flush()
    diffs: list[tuple[str, str, str | None, str | None]] = []

    try:
        account = client.get_account()
        if account.can_withdraw or account.can_withdraw_fiat:
            diffs.append(("permission", "canWithdraw", "false", "true"))
        if not account.can_trade:
            diffs.append(("permission", "canTrade", "true", "false"))

        remote_open = {}
        for o in client.get_open_orders():
            remote_open[o.client_order_id or str(o.order_id)] = o
        local_live = list(
            session.scalars(
                select(OrderRow).where(
                    OrderRow.origin == "LIVE", OrderRow.state.notin_([s.value for s in TERMINAL])
                )
            )
        )
        local_open = {
            o.client_order_id: o
            for o in local_live
            if o.state
            in {
                OrderState.OPEN.value,
                OrderState.PARTIALLY_FILLED.value,
                OrderState.CANCEL_REQUESTED.value,
            }
        }
        for cid, o in remote_open.items():
            if cid not in local_open:
                diffs.append(("order_missing_locally", cid, None, o.status or "open"))
        for cid, row in local_open.items():
            if cid not in remote_open:
                diffs.append(("order_missing_on_exchange", cid, row.state, None))
        for cid, row in local_open.items():
            if cid in remote_open and remote_open[cid].executed_qty != row.executed_qty:
                diffs.append(
                    ("executed_qty", cid, str(row.executed_qty), str(remote_open[cid].executed_qty))
                )
        for row in local_live:
            if row.state == OrderState.UNKNOWN.value:
                diffs.append(("order_unknown", row.client_order_id, row.state, None))

        known = {t for (t,) in session.execute(select(Fill.exchange_trade_id)) if t}
        end = now()
        for pair in pairs:
            for w_start, w_end in windows(end - lookback, end):
                for t in client.get_my_trades(
                    pair,
                    start_ms=int(w_start.timestamp() * 1000),
                    end_ms=int(w_end.timestamp() * 1000),
                ):
                    if t.trade_id not in known:
                        diffs.append(("trade_missing_locally", t.trade_id, None, str(t.qty)))
        run.result = "differences" if diffs else "clean"
    except ConnectorError as exc:
        # An unreadable exchange is not "clean": it is a failed run, and failed halts too.
        run.result = "failed"
        diffs.append(
            (
                "reconcile_failed",
                exc.operation if hasattr(exc, "operation") else "exchange",
                None,
                str(exc.error_class),
            )
        )

    for kind, ref, local, remote in diffs:
        session.add(
            ReconciliationDifference(
                run_id=run.id,
                kind=kind,
                reference=ref[:80],
                local_value=local,
                exchange_value=remote,
            )
        )
    run.differences, run.finished_at = len(diffs), now()
    if run.result == "clean":
        # A run that could not read the exchange recorded a "difference" only to say so. A later
        # clean run supersedes it, otherwise a transient outage would leave a difference nobody can
        # resolve and the Trader could never be resumed. A real data difference (an order or a trade
        # that does not match) is never closed here: that needs the owner.
        stamp = now()
        for stale in session.scalars(
            select(ReconciliationDifference).where(
                ReconciliationDifference.kind == "reconcile_failed",
                ReconciliationDifference.resolved_at.is_(None),
            )
        ):
            stale.resolved_at = stamp
            stale.resolution_note = "superseded by a later clean run (the exchange was unreadable)"
    session.commit()
    if run.result != "clean" and killswitch is not None:
        killswitch.activate("HALT", "reconciler", "reconciler")
    return run
