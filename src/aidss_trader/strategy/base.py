"""The strategy contract (docs/05-MODULE-SPECIFICATIONS/01).

A strategy is a pure function: closed candles, its parameters, and the current
position state in; a signal out. It has no network, database, clock, or random
access, and it cannot reach the connector or the order path. A signal carries no
size, no order type, and no authority: the Intent Builder and the Risk Engine
decide what, if anything, becomes an order.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from aidss_trader.connector.types import Candle


class SignalKind(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class PositionState:
    """Long-only spot: a position is flat or long. `last_exit_at` drives re-entry cooldown."""

    long: bool = False
    entry_price: Decimal | None = None
    last_exit_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Signal:
    kind: SignalKind
    reason: str
    stop_hint: Decimal | None = None
    #: The rule inputs and outputs, as strings, stored on the intent so it explains itself.
    inputs: dict[str, str] = field(default_factory=dict)


class Strategy(Protocol):
    name: str

    def evaluate(
        self, candles: Sequence[Candle], position: PositionState
    ) -> Signal:  # pragma: no cover - protocol
        ...

    def version_id(self) -> str:  # pragma: no cover - protocol
        ...


def snapshot(**values: Any) -> dict[str, str]:
    return {k: ("None" if v is None else str(v)) for k, v in values.items()}
