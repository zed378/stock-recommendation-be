"""Showing a watchlist or an analysis to another account.

The feature is small; the guards are the point. A recommendation carrying a
label and a confidence score, sent from one person to another, is the closest
this platform comes to distributing investment research - so the tests here are
mostly about who can send what, and who can never re-send it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from aidss.collab import sharing
from aidss.db.models import (
    AIConversation,
    AnalysisResult,
    Asset,
    ShareKind,
    User,
    UserStatus,
    Watchlist,
)


def account(session, email: str, status: UserStatus = UserStatus.ACTIVE) -> User:
    user = User(email=email, password_hash="x", status=status)
    session.add(user)
    session.flush()
    return user


def a_watchlist(session, owner: User, name: str = "Banks") -> Watchlist:
    row = Watchlist(user_id=owner.id, name=name)
    session.add(row)
    session.flush()
    return row


def an_analysis(session, owner: User | None) -> AnalysisResult:
    asset = session.scalar(select(Asset).where(Asset.ticker == "BBRI"))
    if asset is None:
        asset = Asset(ticker="BBRI", exchange="IDX", name="BBRI")
        session.add(asset)
        session.flush()

    conversation_id = None
    if owner is not None:
        conversation = AIConversation(user_id=owner.id, context_type="asset_analysis")
        session.add(conversation)
        session.flush()
        conversation_id = conversation.id

    result = AnalysisResult(
        asset_id=asset.id,
        analysis_type="multi_agent",
        conversation_id=conversation_id,
        context_snapshot={"result": {"ticker": "BBRI"}},
    )
    session.add(result)
    session.flush()
    return result


# --- who may share what -----------------------------------------------------


def test_a_watchlist_can_be_shared_with_a_named_account(session) -> None:
    owner = account(session, "owner@example.com")
    account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)

    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    assert row.revoked_at is None


def test_you_cannot_share_what_you_do_not_own(session) -> None:
    owner = account(session, "owner@example.com")
    stranger = account(session, "stranger@example.com")
    account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)

    with pytest.raises(sharing.ShareRefused):
        sharing.share(
            session,
            owner_id=stranger.id,
            recipient_email="friend@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )


def test_a_recipient_cannot_re_share(session) -> None:
    """The property the whole design rests on. If a recipient can pass it on,
    the audience stops being knowable and the redistribution question stops
    having an answer."""
    owner = account(session, "owner@example.com")
    friend = account(session, "friend@example.com")
    account(session, "third@example.com")
    watchlist = a_watchlist(session, owner)
    sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    with pytest.raises(sharing.ShareRefused):
        sharing.share(
            session,
            owner_id=friend.id,
            recipient_email="third@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )


def test_an_analysis_nobody_requested_is_shareable_by_nobody(session) -> None:
    """A scheduled run has no requester. Treating "no owner" as "anyone" is the
    unsafe reading of an ambiguous case."""
    owner = account(session, "owner@example.com")
    account(session, "friend@example.com")
    orphan = an_analysis(session, owner=None)

    with pytest.raises(sharing.ShareRefused):
        sharing.share(
            session,
            owner_id=owner.id,
            recipient_email="friend@example.com",
            kind=ShareKind.ANALYSIS,
            subject_id=orphan.id,
        )


def test_an_unknown_address_and_a_non_user_look_identical(session) -> None:
    """Distinguishing them turns this into a way to test whether somebody has
    an account here."""
    owner = account(session, "owner@example.com")
    watchlist = a_watchlist(session, owner)

    with pytest.raises(sharing.ShareRefused) as first:
        sharing.share(
            session,
            owner_id=owner.id,
            recipient_email="nobody@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )
    with pytest.raises(sharing.ShareRefused) as second:
        sharing.share(
            session,
            owner_id=owner.id,
            recipient_email="also-nobody@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )

    assert str(first.value) == str(second.value)


def test_you_cannot_share_with_yourself(session) -> None:
    owner = account(session, "owner@example.com")
    watchlist = a_watchlist(session, owner)

    with pytest.raises(sharing.ShareRefused):
        sharing.share(
            session,
            owner_id=owner.id,
            recipient_email="owner@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )


def test_a_banned_account_cannot_receive(session) -> None:
    owner = account(session, "owner@example.com")
    account(session, "banned@example.com", status=UserStatus.BANNED)
    watchlist = a_watchlist(session, owner)

    with pytest.raises(sharing.ShareRefused):
        sharing.share(
            session,
            owner_id=owner.id,
            recipient_email="banned@example.com",
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )


# --- withdrawing ------------------------------------------------------------


def test_revoking_removes_access_but_keeps_the_record(session) -> None:
    """"This was shared and then taken back" is the question the list exists to
    answer, and a row that vanishes cannot answer it."""
    owner = account(session, "owner@example.com")
    friend = account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)
    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    assert sharing.revoke(session, owner_id=owner.id, share_id=row.id) is True
    assert (
        sharing.readable(
            session,
            recipient_id=friend.id,
            kind=ShareKind.WATCHLIST,
            subject_id=watchlist.id,
        )
        is False
    )
    assert len(sharing.outgoing(session, owner.id)) == 1


def test_only_the_owner_can_revoke(session) -> None:
    owner = account(session, "owner@example.com")
    friend = account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)
    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    assert sharing.revoke(session, owner_id=friend.id, share_id=row.id) is False


def test_re_sharing_something_withdrawn_reinstates_it(session) -> None:
    """The unique constraint exists to stop duplicates, not to make a
    withdrawal permanent."""
    owner = account(session, "owner@example.com")
    account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)
    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )
    sharing.revoke(session, owner_id=owner.id, share_id=row.id)

    again = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    assert again.id == row.id
    assert again.revoked_at is None


def test_incoming_hides_what_was_withdrawn(session) -> None:
    owner = account(session, "owner@example.com")
    friend = account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner)
    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )
    sharing.revoke(session, owner_id=owner.id, share_id=row.id)

    assert sharing.incoming(session, friend.id) == []


# --- reading a shared analysis ----------------------------------------------


def test_a_shared_analysis_carries_the_recipients_caveat(session) -> None:
    """A different caveat from the owner's, deliberately: the recipient did not
    choose the issuer and did not set the horizon it was framed for."""
    assert "rather than yours" in sharing.RECIPIENT_CAVEAT
    assert "licensed" in sharing.RECIPIENT_CAVEAT
    assert "revoke" in sharing.RECIPIENT_CAVEAT


def test_reading_requires_a_live_grant(session) -> None:
    owner = account(session, "owner@example.com")
    friend = account(session, "friend@example.com")
    result = an_analysis(session, owner)

    assert (
        sharing.readable(
            session, recipient_id=friend.id, kind=ShareKind.ANALYSIS, subject_id=result.id
        )
        is False
    )

    sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.ANALYSIS,
        subject_id=result.id,
    )

    assert (
        sharing.readable(
            session, recipient_id=friend.id, kind=ShareKind.ANALYSIS, subject_id=result.id
        )
        is True
    )


def test_a_share_points_at_the_original_not_a_copy(session) -> None:
    """A copy would turn every share into a second authoritative version of an
    analysis, which is the thing §16.1 rules out for translations."""
    owner = account(session, "owner@example.com")
    account(session, "friend@example.com")
    watchlist = a_watchlist(session, owner, name="Banks")
    row = sharing.share(
        session,
        owner_id=owner.id,
        recipient_email="friend@example.com",
        kind=ShareKind.WATCHLIST,
        subject_id=watchlist.id,
    )

    watchlist.name = "Bank BUMN"
    session.flush()

    assert sharing._subject_label(session, row.kind, row.subject_id) == "Bank BUMN"


# --- the endpoints ----------------------------------------------------------


def test_reading_an_unshared_analysis_is_a_404(client, auth_headers) -> None:
    """404 rather than 403: distinguishing them tells a caller which analysis
    ids exist."""
    response = client.get(f"/shares/analysis/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404


def test_the_share_list_is_scoped_to_the_caller(client, auth_headers) -> None:
    assert client.get("/shares/incoming", headers=auth_headers).json() == []
    assert client.get("/shares/outgoing", headers=auth_headers).json() == []


def test_revoking_someone_elses_share_is_a_404(client, auth_headers) -> None:
    response = client.delete(f"/shares/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404
