"""Logging that cannot stop a stop.

A log handler can fail: a full disk, a broken pipe, a handler bug. Python's stock handlers swallow
that, but a custom or JSON handler may raise, and a raise inside an `except` block in the trading
loop would skip the protective steps after it. Everything in the trading path that logs goes through
here, so a failing log is lost, and the stops and the kill switch still run (R11).
"""

from __future__ import annotations

import logging
from typing import Any


def safe_log(logger: logging.Logger, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
    try:
        logger.log(level, msg, *args, **kwargs)
    except Exception:  # noqa: BLE001 - the whole point is that nothing here may propagate
        pass
