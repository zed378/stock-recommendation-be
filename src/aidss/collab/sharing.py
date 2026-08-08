"""Showing a watchlist or an analysis to another account.

The feature is small. The care around it is not, and the reason is in Section 26: a
recommendation carrying a label and a confidence score, sent from one person to
another, is closer to distributing investment research than anything else this
platform does. That does not make it impermissible - it makes it the one
surface where who receives what has to stay answerable.

Four rules follow, and each closes a specific way this could go wrong:

  * **Named recipients only, never links.** A shareable URL is a bearer token
    for financial analysis about a named company. It forwards itself, and it
    cannot be revoked once it is in a group chat.
  * **A grant, not a copy.** The row points at the original, so the recipient
    sees the current analysis rather than a fossil, and revoking removes access
    to the thing instead of to one snapshot of it.
  * **Read-only, and the disclaimer travels.** A shared analysis arrives with
    the same caveat the owner saw. A reader who did not run it has *less*
    context than one who did, not more, so dropping the caveat here would be
    worse than dropping it anywhere else.
  * **Both sides are auditable.** Owner and recipient can each list what is
    shared, and revocation is recorded rather than erased.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aidss.db.models import (
    AnalysisResult,
    Asset,
    SharedItem,
    ShareKind,
    User,
    UserStatus,
    Watchlist,
)

#: Attached to every shared analysis when it is read by the recipient. Not the
#: same sentence the owner saw: the recipient did not choose the issuer, did not
#: set the parameters, and may not know what the platform is.
RECIPIENT_CAVEAT = (
    "Shared with you by another user of this platform. This is AI-generated "
    "analysis for informational purposes, not investment advice from a licensed "
    "adviser, and it was produced for the sender's stated horizon and risk "
    "appetite rather than yours. The sender cannot change it and neither can "
    "you - it is a view of the original analysis, which its owner may re-run or "
    "revoke at any time."
)


class ShareRefused(Exception):
    """The share cannot be created, with a reason meant for the sender."""


@dataclass(frozen=True, slots=True)
class ShareView:
    """One share, resolved enough for a list screen."""

    item: SharedItem
    #: Who the other party is - the recipient when listing outgoing shares, the
    #: owner when listing incoming ones.
    counterpart_email: str
    label: str

    def as_payload(self) -> dict[str, Any]:
        return {
            **self.item.as_payload(),
            "counterpart_email": self.counterpart_email,
            "label": self.label,
        }


def _subject_label(session: Session, kind: ShareKind, subject_id: uuid.UUID) -> str:
    if kind is ShareKind.WATCHLIST:
        row = session.get(Watchlist, subject_id)
        return row.name if row else "(deleted)"
    result = session.get(AnalysisResult, subject_id)
    if result is None:
        return "(deleted)"
    asset = session.get(Asset, result.asset_id)
    return f"{asset.ticker if asset else '?'} · {result.generated_at:%Y-%m-%d}"


def _owns(session: Session, user_id: uuid.UUID, kind: ShareKind, subject_id: uuid.UUID) -> bool:
    """Whether this user may share this thing.

    Checked against ownership rather than readability. A recipient must not be
    able to re-share what was shared with them: that is precisely how an
    audience stops being knowable, and the whole design above depends on it
    staying knowable.
    """
    if kind is ShareKind.WATCHLIST:
        row = session.get(Watchlist, subject_id)
        return row is not None and row.user_id == user_id

    result = session.get(AnalysisResult, subject_id)
    if result is None:
        return False
    # An analysis belongs to whoever asked for it, recorded on its conversation.
    # Analyses produced by a scheduled run have no requester and are shareable
    # by nobody, which is the safe reading of an ambiguous case.
    return _analysis_owner(session, result) == user_id


def _analysis_owner(session: Session, result: AnalysisResult) -> uuid.UUID | None:
    from aidss.db.models import AIConversation

    if result.conversation_id is None:
        return None
    conversation = session.get(AIConversation, result.conversation_id)
    return conversation.user_id if conversation else None


def share(
    session: Session,
    *,
    owner_id: uuid.UUID,
    recipient_email: str,
    kind: ShareKind,
    subject_id: uuid.UUID,
    note: str | None = None,
) -> SharedItem:
    recipient = session.scalar(
        select(User).where(User.email == recipient_email.strip().lower())
    )
    if recipient is None:
        # Deliberately the same wording whether the address exists or is simply
        # not a user here. Distinguishing them turns this into a way to test
        # whether somebody has an account.
        raise ShareRefused("No account here accepts shares at that address.")
    if recipient.id == owner_id:
        raise ShareRefused("That is your own account.")
    if recipient.status is not UserStatus.ACTIVE:
        raise ShareRefused("That account cannot receive shares right now.")
    if not _owns(session, owner_id, kind, subject_id):
        raise ShareRefused("You can only share something you own.")

    existing = session.scalar(
        select(SharedItem).where(
            SharedItem.owner_id == owner_id,
            SharedItem.recipient_id == recipient.id,
            SharedItem.kind == kind,
            SharedItem.subject_id == subject_id,
        )
    )
    if existing is not None:
        # Re-sharing something previously withdrawn reinstates it rather than
        # failing. The unique constraint exists to stop duplicates, not to make
        # a revoked share permanent.
        existing.revoked_at = None
        existing.note = note
        session.flush()
        return existing

    row = SharedItem(
        owner_id=owner_id,
        recipient_id=recipient.id,
        kind=kind,
        subject_id=subject_id,
        note=note,
    )
    session.add(row)
    session.flush()
    return row


def revoke(session: Session, *, owner_id: uuid.UUID, share_id: uuid.UUID) -> bool:
    """Withdraw a share. Only the owner can, and only their own."""
    row = session.scalar(
        select(SharedItem).where(SharedItem.id == share_id, SharedItem.owner_id == owner_id)
    )
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    session.flush()
    return True


def outgoing(session: Session, owner_id: uuid.UUID) -> list[ShareView]:
    rows = session.scalars(
        select(SharedItem)
        .where(SharedItem.owner_id == owner_id)
        .order_by(SharedItem.created_at.desc())
    ).all()
    return [_view(session, row, row.recipient_id) for row in rows]


def incoming(session: Session, recipient_id: uuid.UUID) -> list[ShareView]:
    rows = session.scalars(
        select(SharedItem)
        .where(SharedItem.recipient_id == recipient_id, SharedItem.revoked_at.is_(None))
        .order_by(SharedItem.created_at.desc())
    ).all()
    return [_view(session, row, row.owner_id) for row in rows]


def _view(session: Session, row: SharedItem, counterpart_id: uuid.UUID) -> ShareView:
    other = session.get(User, counterpart_id)
    return ShareView(
        item=row,
        counterpart_email=other.email if other else "(deleted)",
        label=_subject_label(session, row.kind, row.subject_id),
    )


def readable(
    session: Session, *, recipient_id: uuid.UUID, kind: ShareKind, subject_id: uuid.UUID
) -> bool:
    """Whether this account currently has a live grant for this subject."""
    return (
        session.scalar(
            select(SharedItem).where(
                SharedItem.recipient_id == recipient_id,
                SharedItem.kind == kind,
                SharedItem.subject_id == subject_id,
                SharedItem.revoked_at.is_(None),
            )
        )
        is not None
    )
