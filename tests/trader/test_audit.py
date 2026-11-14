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
