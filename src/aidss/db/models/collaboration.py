"""Scheduled issuer events, and things one investor shows another.

Two tables that have nothing to do with each other technically and one thing in
common by design: both are places where this platform stops being a private
tool and starts carrying information *about* a company or *to* another person.
Both therefore need the same care about what they are allowed to say.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aidss.db.base import Base, enum_column, new_uuid, utcnow


class AgendaKind(StrEnum):
    """What kind of scheduled event this is.

    A closed vocabulary for the same reason `AlertKind` is one: an agenda entry
    reaches a reader as a dated fact about a company, and a free-text `kind`
    lets a future caller write "buy before this date" into a field that renders
    on a calendar.
    """

    EARNINGS = "earnings"
    #: General meeting of shareholders.
    RUPS = "rups"
    DIVIDEND = "dividend"
    #: Ex-date, record date, payment date - the ones that move a quoted price
    #: mechanically rather than because anybody changed their mind.
    EX_DATE = "ex_date"
    STOCK_SPLIT = "stock_split"
    RIGHTS_ISSUE = "rights_issue"
    #: Anything scheduled and disclosed that does not fit above.
    OTHER = "other"


class AgendaSource(StrEnum):
    #: Read from the exchange or an issuer disclosure.
    EXCHANGE = "exchange"
    #: Extracted from a tagged news item that announced a date.
    NEWS = "news"
    #: Typed by an operator.
    MANUAL = "manual"


class IssuerAgenda(Base):
    """One dated, disclosed event for one issuer.

    Keyed on ticker rather than `asset_id`, like the market scan: the calendar
    covers the whole exchange, and most issuers on it have no `Asset` row.

    **This table states schedules, never consequences.** "TLKM reports on 30
    April" is a fact. "TLKM reports on 30 April, consider buying before" is a
    trading signal wearing a calendar entry's clothes, and the absence of any
    column it could live in is the guard.
    """

    __tablename__ = "issuer_agenda"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[AgendaKind] = mapped_column(enum_column(AgendaKind))

    #: The date the event is scheduled for, in exchange time. A date rather
    #: than a timestamp: almost nothing here is announced to the hour, and a
    #: timestamp would invent a precision the disclosure does not have.
    scheduled_for: Mapped[date] = mapped_column(index=True)

    #: What the disclosure said, kept close to its own words.
    title: Mapped[str] = mapped_column(String(400))
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    source: Mapped[AgendaSource] = mapped_column(enum_column(AgendaSource))
    #: Where a reader can check it. An undated claim about a company with no
    #: link back is a rumour the platform is repeating.
    source_url: Mapped[str | None] = mapped_column(String(600), default=None)

    #: True once the date has passed unconfirmed. Kept rather than deleted:
    #: "the meeting was scheduled for the 12th and did not happen" is itself
    #: information, and a row that vanishes cannot say it.
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        # One event of one kind per issuer per day. Re-importing a calendar
        # updates rather than duplicating, the same rule the market scan uses.
        UniqueConstraint("ticker", "kind", "scheduled_for", name="uq_agenda_event"),
        Index("ix_agenda_upcoming", "scheduled_for", "ticker"),
    )


class ShareKind(StrEnum):
    WATCHLIST = "watchlist"
    ANALYSIS = "analysis"


class SharedItem(Base):
    """One thing an investor has chosen to show another investor.

    **Sharing is a grant, not a copy.** The row points at the original, so a
    watchlist the owner edits stays current for whoever it was shared with, and
    revoking removes access to the thing itself rather than to one snapshot of
    it. A copy would also quietly turn every share into a second authoritative
    version of an analysis, which Section 17.1 rules out for translations for exactly
    the same reason.

    **Recipients are named accounts, not links.** A shareable URL is a bearer
    token for financial analysis about a named company, forwardable by anyone
    who receives it and unrevokable once it is in a group chat. Naming the
    recipient keeps the audience knowable, which is the only property that
    makes the redistribution question answerable at all (Section 26).
    """

    __tablename__ = "shared_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    kind: Mapped[ShareKind] = mapped_column(enum_column(ShareKind))
    #: The watchlist or analysis_result being shared. Not a foreign key,
    #: because it points at one of two tables; the route resolves it against
    #: the kind and refuses anything the owner does not own.
    subject_id: Mapped[uuid.UUID] = mapped_column()

    #: Optional line from the sender. Free text, and therefore never fed to a
    #: model as anything but data (Section 26, prompt injection).
    note: Mapped[str | None] = mapped_column(String(500), default=None)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    #: Set rather than deleted, so "this was shared and then withdrawn" stays
    #: answerable - which matters when the question is who saw what.
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)

    __table_args__ = (
        UniqueConstraint(
            "owner_id", "recipient_id", "kind", "subject_id", name="uq_share_target"
        ),
        Index("ix_share_recipient", "recipient_id", "revoked_at"),
    )

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "subject_id": str(self.subject_id),
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }
