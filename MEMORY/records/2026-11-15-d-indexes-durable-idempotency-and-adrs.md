# 2026-11-15 - Task D: dashboard indexes (P5), durable Idempotency-Key replay, ADR-050 to 052

## Changed
- `db/models.py`: indexes for the dashboard and list queries on `order`, `order_intent`, `approval`, `ledger_entry`, `trading_event`, `reconciliation_run`, `reconciliation_difference`, `fill`, `audit_log`; new `IdempotencyRecord` (`trading.idempotency_key`).
- Migration `0008_indexes_idempotency` (additive; creates the table and indexes, grants `SELECT, INSERT, DELETE` on the table to `trader_rw` on PostgreSQL only).
- `api/app.py`: `/dashboard` filters open orders in SQL (it loaded every LIVE order before); `/intents` loads only the approvals for the 200 intents it returns (it loaded all approvals); `_Replays` is backed by the new table with an in-memory fallback.
- `tests/trader/test_liveness_monitor.py`: the fake Telegram token is assembled at runtime. The S17 secret scanner flagged the literal.
- ADR-050 (pinning), ADR-051 (durable replay), ADR-052 (frozen feed), all `proposed`.

## Verified
- `pytest tests/trader tests/test_architecture_constraints.py`: 496 passed, 6 deselected, 1 xfailed (S13, strict). `ruff check` clean on the touched paths.
- New `tests/trader/test_d_gaps.py`: the answer is written to the table and the key is stored hashed; a fresh store reads it (stands in for a restart); an expired row is ignored; a missing table falls back to memory; every declared index exists on SQLite.

## Not verified
- Nothing ran on PostgreSQL: the `-m postgres` privilege tests, migration `0008` there, and `EXPLAIN (ANALYZE, BUFFERS)`. `test_p5_dashboard_open_orders_query_uses_an_index` exists but is skipped without `AIDSS_TRADER_TEST_OWNER_URL`. P5 is therefore NOT met on evidence.
- A real process restart was not exercised; a second `_Replays` over the same database stands in for it.
- Nothing prunes `idempotency_key`.
- D2 (restore rehearsal), D3 (checklist), and the VM steps of Tasks A and B were not done.