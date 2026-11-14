"""Privilege boundary (FR-T26, NFR-T13). Needs a real PostgreSQL, so opt-in: `pytest -m postgres`.

Set AIDSS_TRADER_TEST_OWNER_URL (a superuser or trader_owner that can run the
migration) and AIDSS_TRADER_TEST_RW_URL (role trader_rw), after running
deploy/trader/bootstrap.sql. NOT YET RUN: no PostgreSQL was available when this
was written, so these assertions are unverified until someone runs them.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.postgres

OWNER = os.environ.get("AIDSS_TRADER_TEST_OWNER_URL")
RW = os.environ.get("AIDSS_TRADER_TEST_RW_URL")


@pytest.fixture(scope="module")
def engines():
    if not (OWNER and RW):
        pytest.skip("AIDSS_TRADER_TEST_OWNER_URL / AIDSS_TRADER_TEST_RW_URL not set")
    return create_engine(OWNER), create_engine(RW)


def _denied(engine, sql: str) -> bool:
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except DBAPIError:
        return True
    return False


def test_rw_can_append_but_not_change_or_remove_audit_rows(engines) -> None:
    _, rw = engines
    insert = (
        "INSERT INTO trading.audit_log (at, actor, action, prev_hash, hash) "
        "VALUES (now(), 'test', 'priv.check', repeat('0',64), "
        "md5(random()::text) || md5(random()::text))"
    )
    with rw.begin() as conn:
        conn.execute(text(insert))
    assert _denied(rw, "UPDATE trading.audit_log SET actor = 'x'")
    assert _denied(rw, "DELETE FROM trading.audit_log")


def test_rw_cannot_modify_a_risk_limit_version(engines) -> None:
    _, rw = engines
    assert _denied(rw, "UPDATE trading.risk_limit SET set_by = 'x'")
    assert _denied(rw, "DELETE FROM trading.risk_limit")


def test_rw_cannot_write_outside_the_trading_schema(engines) -> None:
    _, rw = engines
    assert _denied(rw, "CREATE TABLE public.should_not_exist (id int)")
    assert _denied(rw, "CREATE TABLE trading.should_not_exist (id int)")
