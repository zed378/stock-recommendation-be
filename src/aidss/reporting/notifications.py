"""Notification service (Phase 8, Section 9 - Notification).

Alerts about the system, never about what to do with money. Section 9 is
explicit that this is "not a trading signal - e.g. 'new analysis available',
'important news'", and the event vocabulary below is closed for exactly that
reason: there is no event type that could carry an instruction, so no future
caller can invent one by passing a different string.

Delivery goes through channel adapters. Only an in-database channel exists
today; email and push slot in behind the same interface without the service
knowing which is which.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aidss.db.models import Notification, User


class NotificationEvent(StrEnum):
    """The complete set of things this platform notifies about.

    Deliberately closed. Every member describes something that *happened* in
    the system; none of them describes an action the reader should take.
    """

    ANALYSIS_READY = "analysis_ready"
    RECOMMENDATION_UPDATED = "recommendation_updated"
    #: Monitoring observed one of the conditions someone asked to be told
    #: about. Named for the observation, not for what to do about it - the
    #: alerts screen carries the detail and links back to the analysis, where
    #: the confidence and the counter-evidence are.
    MONITORING_ALERT = "monitoring_alert"
    NEWS_INGESTED = "news_ingested"
    SCHEDULE_NEEDS_ATTENTION = "schedule_needs_attention"
    INGESTION_FAILED = "ingestion_failed"
    BUDGET_THRESHOLD_REACHED = "budget_threshold_reached"
    REPORT_READY = "report_ready"


#: Human-readable subjects. Phrased as statements of fact, so no notification
#: can read as a prompt to transact.
SUBJECTS: dict[NotificationEvent, str] = {
    NotificationEvent.ANALYSIS_READY: "New analysis available",
    NotificationEvent.RECOMMENDATION_UPDATED: "Recommendation updated",
    NotificationEvent.MONITORING_ALERT: "Monitoring raised an alert",
    NotificationEvent.NEWS_INGESTED: "New coverage collected",
    NotificationEvent.SCHEDULE_NEEDS_ATTENTION: "A news schedule needs attention",
    NotificationEvent.INGESTION_FAILED: "Data ingestion failed",
    NotificationEvent.BUDGET_THRESHOLD_REACHED: "AI spend threshold reached",
    NotificationEvent.REPORT_READY: "Report ready",
}


class NotificationChannel(ABC):
    """One delivery mechanism."""

    name: ClassVar[str]

    @abstractmethod
    def deliver(self, user: User, subject: str, message: str) -> bool:
        """Return whether delivery succeeded."""


class DatabaseChannel(NotificationChannel):
    """Stores the notification for the user to read in-app.

    Always available and never fails for reasons outside the platform, which
    makes it the sensible default: an alert about a failing provider should not
    itself depend on an external service.
    """

    name: ClassVar[str] = "in_app"

    def deliver(self, user: User, subject: str, message: str) -> bool:  # noqa: ARG002
        return True


@dataclass(slots=True)
class DeliveryResult:
    notification_id: uuid.UUID
    channel: str
    delivered: bool


class NotificationService:
    def __init__(self, session: Session, channels: list[NotificationChannel] | None = None):
        self._session = session
        self._channels = channels or [DatabaseChannel()]

    def notify(
        self,
        user_id: uuid.UUID,
        event: NotificationEvent,
        message: str,
        *,
        channel: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[DeliveryResult]:
        """Record and deliver one notification.

        The row is written before delivery is attempted, so a notification is
        never lost because a channel was down - it is simply marked as not
        delivered and can be retried.
        """
        user = self._session.get(User, user_id)
        if user is None:
            raise LookupError(f"No user {user_id}")

        subject = SUBJECTS[event]
        targets = [c for c in self._channels if channel is None or c.name == channel]
        if not targets:
            raise LookupError(f"No notification channel named {channel!r}")

        results: list[DeliveryResult] = []
        for target in targets:
            row = Notification(
                user_id=user_id,
                channel=target.name,
                subject=subject,
                message=message,
                status="pending",
                event=event.value,
                context=context or None,
            )
            self._session.add(row)
            self._session.flush()

            delivered = target.deliver(user, subject, message)
            row.status = "delivered" if delivered else "failed"
            results.append(
                DeliveryResult(notification_id=row.id, channel=target.name, delivered=delivered)
            )

        self._session.flush()
        return results

    def unread(self, user_id: uuid.UUID, *, limit: int = 50) -> list[Notification]:
        return self.recent(user_id, limit=limit, include_read=False)

    def recent(
        self, user_id: uuid.UUID, *, limit: int = 50, include_read: bool = False
    ) -> list[Notification]:
        """The user's notifications, unread first by default.

        `include_read` exists because marking one read used to remove it from
        the only endpoint that returned it - so a notification you glanced at
        was gone, and there was no way to answer "what was that alert about an
        hour ago?".
        """
        stmt = select(Notification).where(Notification.user_id == user_id)
        if not include_read:
            stmt = stmt.where(Notification.status == "delivered")
        else:
            # `pending` means the row was written and delivery never completed.
            # Excluded from history because it was never shown to anyone.
            stmt = stmt.where(Notification.status.in_(("delivered", "read")))
        return list(
            self._session.scalars(
                stmt.order_by(Notification.created_at.desc()).limit(limit)
            ).all()
        )

    def unread_count(self, user_id: uuid.UUID) -> int:
        """For the indicator, which needs a number rather than the rows."""
        return int(
            self._session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id,
                    Notification.status == "delivered",
                )
            )
            or 0
        )

    def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        row = self._session.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        if row is None:
            return False
        row.status = "read"
        self._session.flush()
        return True
