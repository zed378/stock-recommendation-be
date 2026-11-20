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

from aidss_trader.db.models import (
    SignalAckRow,
    SignalCandidate,
    SignalConfigRow,
    SignalScan,
    SignalTrade,
)
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

    def last_scan_started(
        self, kind: str | None = None, prefix: str | None = None
    ) -> datetime | None:
        """When the latest scan of this kind (or of kinds starting with `prefix`) began."""
        with self._factory() as s:
            q = select(SignalScan.started_at).order_by(SignalScan.started_at.desc()).limit(1)
            if kind is not None:
                q = q.where(SignalScan.kind == kind)
            if prefix is not None:
                q = q.where(SignalScan.kind.startswith(prefix))
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

    # ---------------------------------------------------------------- 4-hour trades

    def trade_exists(self, signal_id: str) -> bool:
        with self._factory() as s:
            return (
                s.scalar(select(SignalTrade.id).where(SignalTrade.signal_id == signal_id))
                is not None
            )

    def add_trade(self, scan_id: uuid.UUID, row: dict[str, Any]) -> bool:
        """Store a new 4-hour signal. False if its id already exists (a rescan or a restart)."""
        if self.trade_exists(row["signal_id"]):
            return False
        with self._factory() as s:
            s.add(
                SignalTrade(
                    scan_id=scan_id,
                    signal_id=row["signal_id"],
                    strategy=row["strategy"],
                    symbol=row["symbol"],
                    side=row["side"],
                    mode=row["mode"],
                    published=bool(row.get("published", False)),
                    candle_open=row["candle_open"],
                    issued_at=row["issued_at"],
                    score=int(row["score"]),
                    components=row.get("components") or {},
                    entry=Decimal(str(row["entry"])),
                    stop=Decimal(str(row["stop"])),
                    tp1=Decimal(str(row["tp1"])),
                    tp2=Decimal(str(row["tp2"])),
                    tp3=Decimal(str(row["tp3"])),
                    atr=Decimal(str(row["atr"])),
                    btc_bias=str(row.get("btc_bias", ""))[:8],
                    state="PENDING",
                    updated_at=self._now(),
                )
            )
            s.commit()
        return True

    def mark_published(self, signal_id: str) -> None:
        with self._factory() as s:
            row = s.scalar(select(SignalTrade).where(SignalTrade.signal_id == signal_id))
            if row is not None:
                row.published = True
                s.commit()

    def unfinished_trades(self) -> list[dict[str, Any]]:
        """Trades that can still change: not yet closed and not skipped."""
        with self._factory() as s:
            rows = s.scalars(
                select(SignalTrade).where(SignalTrade.state.in_(("PENDING", "OPEN")))
            ).all()
            return [
                {
                    "id": r.id,
                    "signal_id": r.signal_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "candle_open": _aware(r.candle_open),
                    "entry": float(r.entry),
                    "stop": float(r.stop),
                    "tps": (float(r.tp1), float(r.tp2), float(r.tp3)),
                }
                for r in rows
            ]

    def update_trade(self, trade_id: uuid.UUID, outcome: Any, closed_at: datetime | None) -> None:
        def dec(v: float | None) -> Decimal | None:
            return None if v is None else Decimal(str(round(v, 8)))

        with self._factory() as s:
            row = s.get(SignalTrade, trade_id)
            if row is None:
                return
            row.state, row.outcome, row.tp_hits = outcome.state, outcome.outcome, outcome.tp_hits
            row.fill_price = dec(outcome.fill_price)
            row.gross_r, row.net_r = dec(outcome.gross_r), dec(outcome.net_r)
            row.bars_held = outcome.bars_held
            row.closed_at = closed_at
            row.updated_at = self._now()
            s.commit()

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
