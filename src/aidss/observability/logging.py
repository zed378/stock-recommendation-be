"""Structured logging with request correlation (Phase 9, Section 26).

JSON lines, because a log an operator has to grep with a regex is a log nobody
queries. Every record carries the request id, so the twelve lines a single
analysis produces can be pulled back together.

The redaction filter is the part that matters most. Section 26 requires that
credentials never appear in logs, and the reliable way to achieve that is not
to trust every future caller to remember - it is to strip them on the way out.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Propagates through the whole request, including into background work
#: started from it, because ContextVar follows the task rather than the thread.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

#: Keys whose values are replaced wholesale, whatever they contain.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "authorization",
        "api_key",
        "secret",
        "jwt_secret",
        "ai_api_key",
        "finnhub_api_key",
        "alphavantage_api_key",
    }
)

#: Patterns for credentials that appear inside free text rather than as a
#: field - an exception message quoting a URL, for instance.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret)\s*[=:]\s*\S+"),
    # Credentials embedded in a connection string.
    re.compile(r"(?i)://[^:/\s]+:[^@/\s]+@"),
)

REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    """Strip credentials from a value of any shape."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        cleaned = value
        for pattern in _PATTERNS:
            cleaned = pattern.sub(
                lambda m: "://" + REDACTED + "@" if m.group(0).endswith("@") else REDACTED,
                cleaned,
            )
        return cleaned
    return value


class JSONFormatter(logging.Formatter):
    """One JSON object per line, with correlation ids attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        user_id = user_id_var.get()
        if user_id:
            payload["user_id"] = user_id

        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))

        # Anything passed through `extra=` rides along, redacted. The key is
        # checked as well as the value: `extra={"api_key": ...}` arrives as a
        # top-level attribute, so redacting only the value would let the one
        # thing this filter exists to stop walk straight through.
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = REDACTED if key.lower() in SENSITIVE_KEYS else redact(value)

        return json.dumps(payload, default=str, ensure_ascii=False)


_RESERVED = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
        "pathname", "process", "processName", "relativeCreated", "stack_info",
        "taskName", "thread", "threadName",
    }
)


#: Third-party loggers held at WARNING, whatever level the platform runs at.
#:
#: `httpx` logs a line for every outbound request. One monitoring pass over a
#: watchlist of thirteen is thirteen lines, every minute, for ever - roughly
#: twenty thousand a day of "GET ... 200 OK" that nobody will ever read, and
#: which bury the handful of lines that say what the platform actually did.
#:
#: WARNING rather than silence: a failing request still has to be visible, and
#: turning a library off entirely trades one blindness for another.
NOISY_LIBRARIES: tuple[str, ...] = ("httpx", "httpcore", "urllib3", "asyncio")


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install the JSON formatter on the root handler.

    Replaces existing handlers rather than adding to them: two handlers means
    every line twice, once structured and once not, which defeats the point.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(
        JSONFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)

    # Applied after the root level, because setting the root to DEBUG would
    # otherwise turn these back on - which is exactly when the flood is least
    # welcome, since DEBUG is what an operator reaches for when hunting
    # something specific.
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request(request_id: str, user_id: str | None = None) -> None:
    request_id_var.set(request_id)
    user_id_var.set(user_id)


def clear_request() -> None:
    request_id_var.set(None)
    user_id_var.set(None)
