from __future__ import annotations

import pytest
from sqlalchemy import text

from aidss_trader.audit import AuditChainBroken, AuditLogger, redact, verify_chain


def _three(session) -> None:
    log = AuditLogger(session)
    log.record(actor="owner", action="limit.change", after={"max_order_idr": "1"})
    log.record(actor="system:risk", action="breaker.trip", mode="PAPER", correlation_id="c1")
    log.record(actor="owner", action="mode.promote", subject_type="strategy", subject_id="s1")
    session.commit()


def test_an_untouched_chain_verifies(session) -> None:
    _three(session)
    session.expire_all()
    assert verify_chain(session) == 3


def test_altering_a_row_is_detected(session) -> None:
    _three(session)
    session.execute(text("UPDATE audit_log SET action = 'something.else' WHERE seq = 2"))
    session.commit()
    session.expire_all()
    with pytest.raises(AuditChainBroken) as excinfo:
        verify_chain(session)
    assert excinfo.value.seq == 2


def test_removing_a_row_is_detected(session) -> None:
    _three(session)
    session.execute(text("DELETE FROM audit_log WHERE seq = 2"))
    session.commit()
    session.expire_all()
    with pytest.raises(AuditChainBroken) as excinfo:
        verify_chain(session)
    assert excinfo.value.seq == 3


def test_sentinel_secrets_are_redacted_before_they_are_stored(session) -> None:
    AuditLogger(session).record(
        actor="owner",
        action="credential.rotate",
        after={
            "api_key": "SENTINEL-KEY",
            "nested": {"secret": "SENTINEL-SECRET"},
            "kind": "indodax",
        },
    )
    session.commit()
    stored = session.execute(text("SELECT after FROM audit_log")).scalar()
    assert "SENTINEL" not in stored and "indodax" in stored


def test_redact_walks_lists_and_leaves_ordinary_fields() -> None:
    out = redact({"items": [{"token": "x", "pair": "BTCIDR"}], "uid": 1})
    assert out == {"items": [{"token": "***", "pair": "BTCIDR"}], "uid": "***"}


def _forked(session) -> tuple[str, str, str]:
    """Rows 1 and 2 chained normally; row 3 chains to row 1 (a fork; row 2 is a dead end); row 4
    follows row 3. Returns (parent hash, sibling hash, child hash)."""
    from datetime import UTC, datetime

    from aidss_trader.audit.log import _fields, _hash
    from aidss_trader.db.models import AuditLog

    log = AuditLogger(session)
    first = log.record(actor="a", action="x")
    second = log.record(actor="b", action="y")
    child = AuditLog(
        at=datetime.now(UTC),
        actor="c",
        action="z",
        prev_hash=first.hash,
        hash="",
    )
    child.hash = _hash(first.hash, _fields(child))
    session.add(child)
    session.flush()
    log.record(actor="d", action="after")
    session.commit()
    session.expire_all()
    return first.hash, second.hash, child.hash


def test_an_unlisted_fork_is_detected(session, monkeypatch) -> None:
    _forked(session)
    monkeypatch.setattr("aidss_trader.audit.log.KNOWN_FORKS", {})
    with pytest.raises(AuditChainBroken) as excinfo:
        verify_chain(session)
    assert excinfo.value.seq == 3


def test_a_listed_fork_is_accepted_but_nothing_else_about_it(session, monkeypatch) -> None:
    parent, sibling, child = _forked(session)
    monkeypatch.setattr("aidss_trader.audit.log.KNOWN_FORKS", {3: (parent, sibling, child)})
    assert verify_chain(session) == 4
    # a different child hash, parent or sibling than the recorded ones is not the accepted fork
    for wrong in (
        (parent, sibling, "0" * 64),
        ("0" * 64, sibling, child),
        (parent, "0" * 64, child),
    ):
        monkeypatch.setattr("aidss_trader.audit.log.KNOWN_FORKS", {3: wrong})
        with pytest.raises(AuditChainBroken):
            verify_chain(session)


def test_an_altered_row_after_an_accepted_fork_is_still_detected(session, monkeypatch) -> None:
    parent, sibling, child = _forked(session)
    monkeypatch.setattr("aidss_trader.audit.log.KNOWN_FORKS", {3: (parent, sibling, child)})
    session.execute(text("UPDATE audit_log SET action = 'tampered' WHERE seq = 4"))
    session.commit()
    session.expire_all()
    with pytest.raises(AuditChainBroken) as excinfo:
        verify_chain(session)
    assert excinfo.value.seq == 4


def test_the_recorded_production_forks_are_five_well_formed_entries() -> None:
    from aidss_trader.audit.log import KNOWN_FORKS

    assert sorted(KNOWN_FORKS) == [1423, 1492, 1638, 1679, 1982]
    for parent, sibling, child in KNOWN_FORKS.values():
        assert all(
            len(h) == 64 and set(h) <= set("0123456789abcdef") for h in (parent, sibling, child)
        )
        assert len({parent, sibling, child}) == 3
