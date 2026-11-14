from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidss_trader.lease import LeaseHolder

T0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


def test_first_instance_takes_it_and_second_is_refused(session) -> None:
    a, b = LeaseHolder("a", 15), LeaseHolder("b", 15)
    assert a.acquire(session, now=T0) is True
    assert b.acquire(session, now=T0 + timedelta(seconds=1)) is False


def test_holder_renews_its_own_lease(session) -> None:
    a = LeaseHolder("a", 15)
    assert a.acquire(session, now=T0)
    assert a.acquire(session, now=T0 + timedelta(seconds=5))
    assert LeaseHolder("b", 15).acquire(session, now=T0 + timedelta(seconds=14)) is False


def test_another_instance_takes_over_only_after_expiry(session) -> None:
    a, b = LeaseHolder("a", 15), LeaseHolder("b", 15)
    a.acquire(session, now=T0)
    assert b.acquire(session, now=T0 + timedelta(seconds=15)) is False  # not yet expired
    assert b.acquire(session, now=T0 + timedelta(seconds=16)) is True
    # The old holder, once it comes back, is refused and must not trade.
    assert a.acquire(session, now=T0 + timedelta(seconds=17)) is False


def test_release_lets_another_instance_start_immediately(session) -> None:
    a, b = LeaseHolder("a", 15), LeaseHolder("b", 15)
    a.acquire(session, now=T0)
    assert a.release(session) is True
    assert b.acquire(session, now=T0 + timedelta(seconds=1)) is True


def test_a_non_holder_cannot_release(session) -> None:
    a, b = LeaseHolder("a", 15), LeaseHolder("b", 15)
    a.acquire(session, now=T0)
    assert b.release(session) is False
    assert a.current(session).holder == "a"
