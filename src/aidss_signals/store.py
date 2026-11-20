"""The worker's window onto the database (ADR-066).

It connects as its own role, `signals_rw`, which can read the settings and add scans, scored coins
and acknowledgements and nothing else in the Trader's schema. The settings are the owner's, edited
on the operator screen; the worker never writes them. Every scored coin is kept, with whether it
met the score, so the history shows how close the others came.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aidss_trader.db.models import SignalAckRow, SignalCandidate, SignalConfigRow, SignalScan
from aidss_trader.signals_config import SignalSettings, get_signal_settings


def _aware(v: datetime | None) -> datetime | None:
    return None if v is None else (v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC))


class SignalStore:
    def __init__(self, factory: sessionmaker[Session], now: Callable[[], datetime] | None = None):
        self._factory = factory
        self._now = now or (lambda: datetime.now(UTC))

    def load_settings(self) -> tuple[SignalSettings, datetime | None]:
        """The owner's settings and the time a scan was last requested (None if never)."""
        with self._factory() as s:
            row = s.get(SignalConfigRow, 1)
            if row is None:
                return SignalSettings(), None
            return get_signal_settings(s), _aware(row.run_requested_at)

    def last_scan_started(self, kind: str | None = None) -> datetime | None:
        with self._factory() as s:
            q = select(SignalScan.started_at).order_by(SignalScan.started_at.desc()).limit(1)
            if kind is not None:
                q = q.where(SignalScan.kind == kind)
            return _aware(s.scalar(q))

    def begin_scan(self, kind: str, mode: str) -> uuid.UUID:
        scan_id = uuid.uuid4()
        with self._factory() as s:
            s.add(
                SignalScan(
                    id=scan_id, kind=kind, status="RUNNING", mode=mode, started_at=self._now()
                )
            )
            s.commit()
        return scan_id

    def finish_scan(
        self,
        scan_id: uuid.UUID,
        *,
        status: str,
        universe: list[str],
        outcomes: dict[str, str],
        errors: list[str],
        ai_calls: int,
        signals: int,
    ) -> None:
        with self._factory() as s:
            scan = s.get(SignalScan, scan_id)
            if scan is None:
                return
            scan.status, scan.finished_at = status, self._now()
            scan.universe, scan.outcomes, scan.errors = universe, outcomes, errors
            scan.ai_calls, scan.signals = ai_calls, signals
            s.commit()

    def save_candidate(self, scan_id: uuid.UUID, mode: str, entry: dict[str, Any]) -> None:
        def dec(key: str) -> Decimal:
            return Decimal(str(round(float(entry.get(key) or 0), 6)))

        with self._factory() as s:
            s.add(
                SignalCandidate(
                    scan_id=scan_id,
                    symbol=entry["symbol"],
                    day=entry["day"],
                    scored_at=self._now(),
                    mode=mode,
                    eligible=bool(entry.get("eligible", False)),
                    reason=str(entry.get("reason", "ok"))[:64],
                    score=dec("score"),
                    max_score=dec("max_score"),
                    score_ratio=dec("score_ratio"),
                    meets_threshold=bool(entry.get("meets_threshold", False)),
                    outcome=str(entry["outcome"])[:24],
                    met=entry.get("met") or {},
                    not_met=entry.get("not_met") or {},
                    ai=entry.get("ai"),
                    levels=entry.get("levels"),
                    signal_id=entry.get("signal_id"),
                )
            )
            s.commit()

    def already_published(self, symbol: str, day: str) -> bool:
        """A signal for this coin and daily candle already went out, so it is not sent twice."""
        with self._factory() as s:
            return (
                s.scalar(
                    select(SignalCandidate.id)
                    .where(
                        SignalCandidate.symbol == symbol,
                        SignalCandidate.day == day,
                        SignalCandidate.outcome == "SIGNAL",
                        SignalCandidate.mode == "PUBLISH",
                    )
                    .limit(1)
                )
                is not None
            )

    def save_ack(self, ack: dict[str, Any]) -> None:
        with self._factory() as s:
            s.add(
                SignalAckRow(
                    signal_id=str(ack.get("signalId", ""))[:64],
                    stage=str(ack.get("stage", ""))[:12],
                    environment=(str(ack["environment"])[:8] if ack.get("environment") else None),
                    status=(str(ack["status"])[:12] if ack.get("status") else None),
                    reason=(str(ack["reason"])[:300] if ack.get("reason") else None),
                    received_at=self._now(),
                )
            )
            s.commit()


class DbState:
    """`State` for database mode: a coin is "decided" once a PUBLISH signal exists for its daily
    candle. SHADOW signals are recorded but never block a later pass, since nothing was sent."""

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    def decided(self, symbol: str, day: str) -> bool:
        return self._store.already_published(symbol, day)

    def mark(self, symbol: str, day: str) -> None:
        return None
