"""Notifier (docs/05-MODULE-SPECIFICATIONS/12, 06-INTEGRATIONS/12).

* The event is stored **before** any delivery is attempted, so a failed send never
  loses it from the app.
* The channel is outbound only. Nothing here reads a reply, and no message can
  approve, deny, or kill.
* A message carries facts only. Payload keys that look like a secret, signature,
  account id, or balance are refused outright, so a careless caller cannot leak
  one; the refusal is a programming error, not a silent scrub.
* `CRITICAL` is never silenced: the owner picks which severities reach the phone,
  but CRITICAL is always included, never collapsed, and retried with backoff until
  delivered. It stays unacknowledged until the owner acknowledges it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss_trader.db.models import TradingEvent

# kind -> (severity, goes to the phone by default). `None` = only if the owner configured it.
CATALOGUE: dict[str, tuple[str, bool | None]] = {
    "intent_awaiting_approval": ("WARN", True),
    "order_filled": ("INFO", False),
    "order_partially_filled": ("INFO", False),
    "order_rejected": ("WARN", None),
    "order_unknown": ("CRITICAL", True),
    "stop_executed": ("WARN", True),
    "exit_unprotected": ("CRITICAL", True),
    "breaker_tripped": ("CRITICAL", True),
    "kill_switch_used": ("CRITICAL", True),
    "reconciliation_difference": ("CRITICAL", True),
    "watchdog_stalled": ("CRITICAL", True),
    "trader_started": ("WARN", True),
    "trader_stopped": ("WARN", True),
    "credential_changed": ("WARN", True),
    "permission_changed": ("CRITICAL", True),
    "mode_changed": ("WARN", True),
    "limit_changed": ("WARN", True),
    "clock_skew": ("WARN", None),
    "connector_degraded": ("WARN", None),
    "approval_not_sent": ("WARN", True),
}

_FORBIDDEN_KEY = re.compile(
    r"key|secret|sign|token|password|uid|account|balance|equity|total|passphrase", re.I
)
_FORBIDDEN_TEXT = re.compile(r"(?i)\b(buy|sell) (now|this)\b|you should")
MAX_TEXT = 400


class UnsafePayload(ValueError):
    pass


class Channel(Protocol):
    def send(self, text: str) -> None:
        """Send one message. Raise on any failure; never swallow it."""


class ChannelError(RuntimeError):
    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class RecordingChannel:
    """The test channel (06-INTEGRATIONS/12): records messages, sends nothing."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.fail = False

    def send(self, text: str) -> None:
        if self.fail:
            raise ChannelError("recording channel set to fail")
        self.messages.append(text)


class TelegramChannel:
    """Outbound Telegram bot messages. Verified against core.telegram.org/bots (2026-11-14):
    method URL form `https://api.telegram.org/bot<token>/sendMessage`; responses carry `ok`
    and, on failure, `description` and `error_code`; the FAQ advises at most about one
    message per second to one chat before 429s. **Not verified:** that a bot may message a
    user who never started it (the owner must press Start once), the maximum text length
    (truncated defensively), and the exact shape of `retry_after`. No live call was made.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        base_url: str = "https://api.telegram.org",
        timeout_s: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._http = httpx.Client(transport=transport, timeout=timeout_s)

    def send(self, text: str) -> None:
        try:
            resp = self._http.post(self._url, data={"chat_id": self._chat_id, "text": text[:4000]})
        except httpx.HTTPError as exc:
            # The URL contains the token: report the class only, never the request.
            raise ChannelError(f"telegram transport error: {type(exc).__name__}") from None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200 and body.get("ok") is True:
            return
        retry = (
            (body.get("parameters") or {}).get("retry_after") if isinstance(body, dict) else None
        )
        raise ChannelError(
            f"telegram refused: http {resp.status_code} code {body.get('error_code')}",
            float(retry) if isinstance(retry, int | float) else None,
        )


def check_payload(payload: Mapping[str, Any] | None, message: str) -> None:
    if len(message) > MAX_TEXT:
        raise UnsafePayload("message too long")
    if _FORBIDDEN_TEXT.search(message):
        raise UnsafePayload("an event states a fact, not a recommendation")
    for key, value in (payload or {}).items():
        if _FORBIDDEN_KEY.search(key):
            raise UnsafePayload(f"payload key {key!r} may carry a secret or a balance")
        if isinstance(value, Mapping):
            check_payload(value, "")


@dataclass(frozen=True, slots=True)
class MobilePolicy:
    """Which severities reach the phone. CRITICAL is always on and cannot be removed."""

    severities: frozenset[str] = frozenset({"WARN", "CRITICAL"})
    configured_optional: frozenset[str] = frozenset()  # kinds the owner switched on

    def __post_init__(self) -> None:
        object.__setattr__(self, "severities", self.severities | {"CRITICAL"})

    def wants(self, kind: str, severity: str) -> bool:
        if severity == "CRITICAL":
            return True
        default = CATALOGUE[kind][1]
        if default is None:
            return kind in self.configured_optional and severity in self.severities
        return default and severity in self.severities


def _now() -> datetime:
    return datetime.now(UTC)


class Notifier:
    def __init__(
        self,
        session: Session,
        channel: Channel | None,
        *,
        policy: MobilePolicy | None = None,
        now: Callable[[], datetime] = _now,
        collapse_window: timedelta = timedelta(minutes=5),
        backoff: tuple[float, ...] = (30, 120, 600, 1800),
        link: str | None = None,
    ) -> None:
        self._s, self._channel, self._now = session, channel, now
        self._policy, self._window, self._backoff = (
            policy or MobilePolicy(),
            collapse_window,
            backoff,
        )
        self._link = link

    def emit(self, kind: str, message: str, payload: dict[str, Any] | None = None) -> TradingEvent:
        if kind not in CATALOGUE:
            raise ValueError(f"unknown event kind {kind!r}")
        severity = CATALOGUE[kind][0]
        check_payload(payload, message)
        now = self._now()
        if severity == "WARN":
            recent = self._s.scalar(
                select(TradingEvent)
                .where(
                    TradingEvent.kind == kind,
                    TradingEvent.message == message,
                    TradingEvent.created_at >= now - self._window,
                )
                .limit(1)
            )
            if recent is not None:
                return recent  # identical WARN collapses; CRITICAL never does
        wants = self._policy.wants(kind, severity) and self._channel is not None
        event = TradingEvent(
            kind=kind,
            severity=severity,
            message=message,
            payload=payload,
            created_at=now,
            mobile="pending" if wants else "none",
            attempts=0,
        )
        self._s.add(event)
        self._s.commit()  # stored before any delivery
        if wants:
            self._deliver(event)
        return event

    def _text(self, event: TradingEvent) -> str:
        text = f"[{event.severity}] {event.message}"
        return f"{text}\n{self._link}" if self._link else text

    def _deliver(self, event: TradingEvent) -> None:
        assert self._channel is not None
        event.attempts += 1
        event.last_attempt_at = self._now()
        try:
            self._channel.send(self._text(event))
            event.mobile = "sent"
        except ChannelError:
            event.mobile = "failed"  # recorded; the in-app event is intact
        self._s.commit()

    def retry_pending(self) -> int:
        """Retry failed CRITICAL deliveries whose backoff has elapsed. Returns attempts made."""
        if self._channel is None:
            return 0
        made, now = 0, self._now()
        failed = self._s.scalars(
            select(TradingEvent).where(
                TradingEvent.severity == "CRITICAL", TradingEvent.mobile == "failed"
            )
        )
        for event in failed:
            idx = min(event.attempts - 1, len(self._backoff) - 1)
            last = event.last_attempt_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if last is None or now - last >= timedelta(seconds=self._backoff[max(idx, 0)]):
                self._deliver(event)
                made += 1
        return made

    def acknowledge(self, event_id: Any, by: str) -> TradingEvent:
        event = self._s.get(TradingEvent, event_id)
        if event is None:
            raise KeyError(event_id)
        if event.acked_at is None:
            event.acked_at, event.acked_by = self._now(), by
            self._s.commit()
        return event
