from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, delete, func, select

from aidss_trader.__main__ import main as trader_main
from aidss_trader.audit import (
    AuditChainBroken,
    chain_head,
    record_head_anchor,
    verify_chain,
    verify_head_anchor,
)
from aidss_trader.auth import AuthFailed, TokenVerifier
from aidss_trader.config import RiskLimits, load_risk_limits, save_risk_limits, unset_risk_fields
from aidss_trader.db.base import Base
from aidss_trader.db.models import AuditLog, RiskLimitVersion


def verifier(handler) -> TokenVerifier:
    return TokenVerifier(
        "https://analysis.test", timeout_s=2, transport=httpx.MockTransport(handler)
    )


def test_a_valid_token_yields_the_user_and_role() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/me" and request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"id": "u1", "email": "x@y", "role": "trader"})

    principal = verifier(ok).verify("tok")
    assert (principal.user_id, principal.role) == ("u1", "trader")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(401, json={"detail": "Invalid token"}),
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, content="<html>"),
        lambda r: httpx.Response(200, json={"id": "u1"}),
        lambda r: httpx.Response(200, json={"id": "u1", "role": "superuser"}),
    ],
)
def test_verification_fails_closed_on_anything_but_a_clear_yes(handler) -> None:
    with pytest.raises(AuthFailed):
        verifier(handler).verify("tok")


def test_an_unreachable_analysis_api_is_a_refusal() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AuthFailed):
        verifier(down).verify("tok")
    with pytest.raises(AuthFailed):
        verifier(down).verify("")


def test_limits_are_unset_until_saved_then_versioned_and_audited(session) -> None:
    assert load_risk_limits(session) is None
    v1 = save_risk_limits(session, RiskLimits(max_order_idr=Decimal("1000")), set_by="owner")
    v2 = save_risk_limits(session, RiskLimits(max_order_idr=Decimal("2000")), set_by="owner")
    assert (v1, v2) == (1, 2)
    loaded = load_risk_limits(session)
    assert loaded.max_order_idr == Decimal("2000")
    assert "risk_per_trade_pct" in unset_risk_fields(loaded)  # everything else is still unset
    assert session.scalar(select(func.count()).select_from(RiskLimitVersion)) == 2
    audit = session.scalars(select(AuditLog).where(AuditLog.action == "limit.change")).all()
    assert len(audit) == 2 and audit[1].before["max_order_idr"] == "1000"
    assert verify_chain(session) == 2


def test_chain_head_reports_the_latest_hash(session) -> None:
    assert chain_head(session) is None
    save_risk_limits(session, RiskLimits(), set_by="owner")
    seq, head = chain_head(session)
    assert seq == 1 and len(head) == 64


def test_external_head_anchor_records_and_is_idempotent(session, tmp_path) -> None:
    anchor_file = tmp_path / "audit-anchors.jsonl"
    assert record_head_anchor(session, anchor_file) is None
    assert verify_head_anchor(session, anchor_file) is None
    assert not anchor_file.exists()

    save_risk_limits(session, RiskLimits(max_order_idr=Decimal("1000")), set_by="owner")
    anchored = record_head_anchor(session, anchor_file)
    assert anchored == chain_head(session)
    lines = anchor_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 1

    # Re-running with unchanged chain head must not append a duplicate line.
    assert record_head_anchor(session, anchor_file) == anchored
    assert len(anchor_file.read_text(encoding="utf-8").splitlines()) == 1
    assert verify_head_anchor(session, anchor_file) == anchored

    # Advancing the chain appends a second anchor.
    save_risk_limits(session, RiskLimits(max_order_idr=Decimal("2000")), set_by="owner")
    anchored2 = record_head_anchor(session, anchor_file)
    assert anchored2[0] == 2
    assert len(anchor_file.read_text(encoding="utf-8").splitlines()) == 2
    assert verify_head_anchor(session, anchor_file) == anchored2


def test_external_head_anchor_detects_db_truncation_or_rewrite(session, tmp_path) -> None:
    anchor_file = tmp_path / "audit-anchors.jsonl"
    save_risk_limits(session, RiskLimits(max_order_idr=Decimal("1000")), set_by="owner")
    save_risk_limits(session, RiskLimits(max_order_idr=Decimal("2000")), set_by="owner")
    record_head_anchor(session, anchor_file)

    # Simulate a DB owner truncating the audit table and rewriting seq=1 with a different hash.
    session.execute(delete(AuditLog))
    session.commit()
    with pytest.raises(AuditChainBroken, match="empty"):
        verify_head_anchor(session, anchor_file)

    save_risk_limits(session, RiskLimits(max_order_idr=Decimal("9999")), set_by="attacker")
    with pytest.raises(AuditChainBroken, match="truncated"):
        record_head_anchor(session, anchor_file)


def test_audit_anchor_cli(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "trader.sqlite"
    anchor_file = tmp_path / "anchors.jsonl"
    db_url = f"sqlite+pysqlite:///{db_path.as_posix()}"

    real_create_engine = create_engine

    def sqlite_engine(url: str, **kwargs):
        return real_create_engine(url, **kwargs).execution_options(
            schema_translate_map={"trading": None}
        )

    engine = sqlite_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    monkeypatch.setenv("AIDSS_TRADER_DATABASE_URL", db_url)
    monkeypatch.setattr("aidss_trader.__main__.create_engine", sqlite_engine)

    # Empty DB succeeds cleanly.
    assert trader_main(["audit-anchor", "--out", str(anchor_file)]) == 0
    assert trader_main(["audit-anchor", "--out", str(anchor_file), "--verify-only"]) == 0

    # Add an audit row and anchor via CLI.
    from sqlalchemy.orm import sessionmaker

    engine = sqlite_engine(db_url)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        save_risk_limits(s, RiskLimits(max_order_idr=Decimal("500")), set_by="owner")
        s.commit()
    engine.dispose()

    assert trader_main(["audit-anchor", "--out", str(anchor_file), "--verify-only"]) == 2
    assert trader_main(["audit-anchor", "--out", str(anchor_file)]) == 0
    assert trader_main(["audit-anchor", "--out", str(anchor_file), "--verify-only"]) == 0
