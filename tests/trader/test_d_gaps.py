"""Stage 2, Task D gaps: durable Idempotency-Key replay (ADR-051, proposed) and the dashboard
indexes (P5). SQLite for the replay store; the index plan check needs PostgreSQL (`-m postgres`).
Mock exchange and test databases only.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, select, text

from aidss_trader.api.app import REPLAY_TTL_S, _Replays
from aidss_trader.db.models import IdempotencyRecord
from tests.trader.test_t5_operator_surface import Api


def test_a_replay_answer_is_written_to_the_database() -> None:
    api = Api()
    headers = {"Authorization": "Bearer tok-trader", "Idempotency-Key": "durable-1"}
    first = api.http.post("/trader/v1/kill", headers=headers, json={"tier": "HALT"})
    assert first.status_code == 200
    with api.factory() as s:
        rows = s.scalars(select(IdempotencyRecord)).all()
    assert len(rows) == 1
    assert rows[0].status_code == 200 and rows[0].response_body.encode() == first.content
    # The key itself is hashed with the caller's token: neither is stored in the clear.
    assert "durable-1" not in rows[0].key_hash and "tok-trader" not in rows[0].key_hash


def test_a_replay_survives_a_fresh_store_standing_in_for_a_restart() -> None:
    api = Api()
    before = _Replays(api.factory)
    before.put("k" * 64, "b" * 64, 200, b'{"ok":true}', "application/json")

    after = _Replays(api.factory)  # new object, empty memory: what a restarted process has
    hit = after.get("k" * 64)
    assert hit is not None
    assert hit[1] == "b" * 64 and hit[2] == 200 and hit[3] == b'{"ok":true}'
    assert after.get("z" * 64) is None


def test_an_expired_database_record_is_not_replayed() -> None:
    from datetime import UTC, datetime, timedelta

    api = Api()
    with api.factory() as s:
        s.add(
            IdempotencyRecord(
                key_hash="o" * 64,
                body_hash="b" * 64,
                status_code=200,
                response_body="{}",
                media_type="application/json",
                created_at=datetime.now(UTC) - timedelta(seconds=REPLAY_TTL_S + 60),
            )
        )
        s.commit()
    assert _Replays(api.factory).get("o" * 64) is None


def test_without_the_table_the_store_falls_back_to_memory() -> None:
    api = Api()
    with api.engine.begin() as conn:
        conn.execute(text("DROP TABLE idempotency_key"))
    store = _Replays(api.factory)
    store.put("m" * 64, "b" * 64, 200, b"x", "text/plain")
    hit = store.get("m" * 64)
    assert hit is not None and hit[3] == b"x"


def test_the_dashboard_indexes_are_declared() -> None:
    api = Api()
    wanted = {
        "order": [("origin", "state"), ("submitted_at",)],
        "order_intent": [("created_at",), ("origin", "pair", "side", "created_at")],
        "approval": [("state",)],
        "ledger_entry": [("at",), ("origin", "at")],
        "trading_event": [("created_at",)],
        "reconciliation_run": [("started_at",)],
        "reconciliation_difference": [("resolved_at",)],
        "fill": [("origin", "executed_at")],
        "audit_log": [("at",)],
    }
    insp = inspect(api.engine)
    for table, shapes in wanted.items():
        have = {tuple(i["column_names"]) for i in insp.get_indexes(table)}
        for shape in shapes:
            assert shape in have, (table, shape)

@pytest.mark.postgres
def test_p5_dashboard_open_orders_query_uses_an_index() -> None:
    url = os.environ.get("AIDSS_TRADER_TEST_OWNER_URL")
    if not url:
        pytest.skip("AIDSS_TRADER_TEST_OWNER_URL not set")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            r[0]
            for r in conn.execute(
                text(
                    "EXPLAIN SELECT * FROM trading.\"order\" WHERE origin = 'LIVE' "
                    "AND state IN ('OPEN','PARTIALLY_FILLED','CANCEL_REQUESTED','UNKNOWN')"
                )
            )
        )
    assert "ix_order_origin_state" in plan or "Index" in plan, plan
