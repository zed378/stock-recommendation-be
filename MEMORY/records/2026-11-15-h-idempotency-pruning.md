# 2026-11-15 — Task H: Opportunistic Pruning of Expired `idempotency_key` Rows (ADR-051)

## What Changed

- `src/aidss_trader/api/app.py`: Added `_Replays._prune_expired(now)` called opportunistically after `_Replays.put()` commits a new record. It deletes rows in `trading.idempotency_key` where `created_at < now - timedelta(seconds=REPLAY_TTL_S)` in a separate transaction wrapped in `try/except`, so a pruning failure never fails or rolls back the API response. Uses `DELETE` already granted to `trader_rw` in migration `0008_indexes_idempotency`.
- `tests/trader/test_d_gaps.py`: Added `test_put_prunes_expired_rows_but_keeps_fresh_rows` and `test_pruning_failure_does_not_fail_put_or_request`.
- `MEMORY/DECISIONS.md`: Updated `ADR-051` implications to document the opportunistic pruning implementation.

## Verified

- `ruff check src tests alembic_trader deploy` → `All checks passed!`.
- `pytest tests/trader/test_d_gaps.py -q` → `7 passed, 1 deselected`.
- `pytest tests/trader tests/test_architecture_constraints.py -q` → `498 passed, 7 deselected, 1 xfailed` (SQLite).

## Not Verified

- Not yet executed on real PostgreSQL 16 (VM) or deployed to `stocks-trader-1`.
