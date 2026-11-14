from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from aidss_trader.audit import chain_head, verify_chain
from aidss_trader.auth import AuthFailed, TokenVerifier
from aidss_trader.config import RiskLimits, load_risk_limits, save_risk_limits, unset_risk_fields
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
