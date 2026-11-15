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
APP = os.environ.get("AIDSS_TRADER_TEST_APP_URL")
MONITOR = os.environ.get("AIDSS_TRADER_TEST_MONITOR_URL")


@pytest.fixture(scope="module")
def engines():
    if not (OWNER and RW):
        pytest.skip("AIDSS_TRADER_TEST_OWNER_URL / AIDSS_TRADER_TEST_RW_URL not set")
    return create_engine(OWNER), create_engine(RW)


@pytest.fixture(scope="module")
def app_engine():
    if not APP:
        pytest.skip("AIDSS_TRADER_TEST_APP_URL not set")
    return create_engine(APP)


@pytest.fixture(scope="module")
def monitor_engine():
    if not MONITOR:
        pytest.skip("AIDSS_TRADER_TEST_MONITOR_URL not set")
    return create_engine(MONITOR)


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


def test_analysis_app_role_owns_public_but_cannot_access_trading_schema(app_engine) -> None:
    with app_engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS public.app_priv_probe (id int)"))
        conn.execute(text("INSERT INTO public.app_priv_probe (id) VALUES (1)"))
        conn.execute(text("DROP TABLE public.app_priv_probe"))
    assert _denied(app_engine, "SELECT * FROM trading.credential")
    assert _denied(app_engine, "SELECT * FROM trading.audit_log")
    assert _denied(app_engine, "SELECT * FROM trading.risk_limit")
    assert _denied(app_engine, "INSERT INTO trading.risk_limit (version, set_by) VALUES (999, 'x')")


def test_monitor_role_reads_heartbeat_only(monitor_engine) -> None:
    with monitor_engine.begin() as conn:
        conn.execute(text("SELECT * FROM trading.lease"))
    assert _denied(monitor_engine, "SELECT * FROM trading.credential")
    assert _denied(monitor_engine, "SELECT * FROM trading.audit_log")
    assert _denied(monitor_engine, "DELETE FROM trading.lease")
    assert _denied(monitor_engine, "CREATE TABLE public.should_not_exist (id int)")
