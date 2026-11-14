"""The order state machine (docs/03-DATA-MODEL/02).

Terminal states have no outgoing transition. `UNKNOWN` is a first-class state: a
timeout or 5xx on a write leaves the outcome unknown, and it is resolved by
querying `clientOrderId`, never by sending the request again (ADR-024).
"""

from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    SUBMITTING = "SUBMITTING"
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


S = OrderState
TERMINAL = frozenset({S.FILLED, S.CANCELLED, S.REJECTED})

TRANSITIONS: dict[OrderState | None, frozenset[OrderState]] = {
    None: frozenset({S.SUBMITTING}),
    S.SUBMITTING: frozenset({S.OPEN, S.REJECTED, S.UNKNOWN, S.FILLED, S.PARTIALLY_FILLED}),
    S.UNKNOWN: frozenset(
        {S.OPEN, S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.REJECTED, S.CANCEL_REQUESTED}
    ),
    S.OPEN: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCEL_REQUESTED, S.CANCELLED}),
    S.PARTIALLY_FILLED: frozenset({S.FILLED, S.CANCEL_REQUESTED, S.CANCELLED}),
    S.CANCEL_REQUESTED: frozenset({S.CANCELLED, S.FILLED, S.UNKNOWN, S.PARTIALLY_FILLED}),
    S.FILLED: frozenset(),
    S.CANCELLED: frozenset(),
    S.REJECTED: frozenset(),
}

_FROM_EXCHANGE = {
    "NEW": S.OPEN,
    "PARTIALLY_FILLED": S.PARTIALLY_FILLED,
    "FILLED": S.FILLED,
    "CANCELLED": S.CANCELLED,
    "REJECTED": S.REJECTED,
}


class IllegalTransition(RuntimeError):
    pass


def can_transition(current: OrderState | None, target: OrderState) -> bool:
    return target in TRANSITIONS[current]


def require_transition(current: OrderState | None, target: OrderState) -> None:
    if not can_transition(current, target):
        raise IllegalTransition(f"{current} -> {target} is not allowed")


def from_exchange(status: str) -> OrderState:
    """Map an Indodax status. An unknown one is an error, never a guess."""
    try:
        return _FROM_EXCHANGE[status]
    except KeyError as exc:
        raise IllegalTransition(f"unrecognised exchange status {status!r}") from exc
