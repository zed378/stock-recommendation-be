"""Normalized errors (docs/06-INTEGRATIONS/01, 08).

The class of an error decides what the Trader does next, so the mapping from
Indodax's codes is in one place and an unrecognised code is never guessed at.

`outcome_unknown` matters more than the class: a timeout or 5xx on a *write*
means the exchange may or may not have acted. The caller resolves that by
querying `clientOrderId`, never by sending the request again (ADR-024).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorClass(StrEnum):
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    CLOCK_SKEW = "CLOCK_SKEW"
    RATE_LIMIT = "RATE_LIMIT"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    REJECTED = "REJECTED"
    MARKET_SUSPENDED = "MARKET_SUSPENDED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    MALFORMED = "MALFORMED"


# Codes appear both with and without a minus sign in Indodax's documentation
# (docs/06-INTEGRATIONS/11, D17), so lookup is by absolute value.
_BY_ABS_CODE: dict[int, ErrorClass] = {
    1001: ErrorClass.UNAVAILABLE,
    1002: ErrorClass.AUTH,
    1021: ErrorClass.CLOCK_SKEW,
    1022: ErrorClass.AUTH,
    1000: ErrorClass.MALFORMED,
    1102: ErrorClass.VALIDATION,
    1109: ErrorClass.VALIDATION,
    1111: ErrorClass.VALIDATION,
    1121: ErrorClass.VALIDATION,
    1130: ErrorClass.VALIDATION,
    1112: ErrorClass.NOT_FOUND,
    1099: ErrorClass.NOT_FOUND,
    2013: ErrorClass.NOT_FOUND,
    2014: ErrorClass.AUTH,
    2015: ErrorClass.PERMISSION,
    1003: ErrorClass.RATE_LIMIT,
    1016: ErrorClass.MARKET_SUSPENDED,
    2010: ErrorClass.REJECTED,
}


def classify(http_status: int | None, code: Any) -> ErrorClass:
    try:
        numeric = abs(int(code))
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None and numeric in _BY_ABS_CODE:
        return _BY_ABS_CODE[numeric]
    if http_status == 429:
        return ErrorClass.RATE_LIMIT
    if http_status is not None and http_status >= 500:
        return ErrorClass.UNAVAILABLE
    # An unknown code is never treated as success or as retryable.
    return ErrorClass.MALFORMED


class ConnectorError(Exception):
    def __init__(
        self,
        error_class: ErrorClass,
        message: str,
        *,
        operation: str,
        code: Any = None,
        http_status: int | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(f"{operation}: {error_class.value}: {message}")
        self.error_class = error_class
        self.operation = operation
        self.code = code
        self.http_status = http_status
        # True for a write that may have reached the exchange. Resolve by query.
        self.outcome_unknown = outcome_unknown
