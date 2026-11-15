# 2026-11-15 — Task D2/D3/D4 & Host-Hardening Local PostgreSQL 18 Rehearsal

## Scope

1. **Task A/B PostgreSQL privilege & isolation rehearsal** (`deploy/trader/bootstrap.sql`, `isolate_analysis_role.sql`, `rollback_analysis_role.sql`, `tests/trader/test_privileges_postgres.py` including new `test_rw_can_insert_but_not_change_backtest_runs` for migration `0007`).
2. **Task D2 (`T6-03`) restore rehearsal** (`deploy/trader/rehearse_restore.sh`).
3. **Task D4 (`P5`) query plan verification** (`EXPLAIN (ANALYZE, BUFFERS)` + `test_p5_dashboard_open_orders_query_uses_an_index`).
4. **Task D3 (`T6-05`) release checklist update** (`docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`).

All PostgreSQL runs in this record executed against an isolated local ephemeral `pgvector/pgvector:pg18` container (`aidss-pg-rehearsal`) on `127.0.0.1:55432`, which was stopped and removed after the rehearsal.

## Evidence

1. **Privilege & isolation rehearsal (`aidss_rehearsal` DB, migrations `0001..0008`):**
   - `bootstrap.sql` -> `alembic -c alembic_trader.ini upgrade head` -> `isolate_analysis_role.sql` succeeded with `ON_ERROR_STOP=1`.
   - `pytest -m postgres tests/trader/test_privileges_postgres.py tests/trader/test_d_gaps.py -v`: **7 passed, 5 deselected in 0.77s** (`test_rw_can_append_but_not_change_or_remove_audit_rows`, `test_rw_cannot_modify_a_risk_limit_version`, `test_rw_can_insert_but_not_change_backtest_runs`, `test_rw_cannot_write_outside_the_trading_schema`, `test_analysis_app_role_owns_public_but_cannot_access_trading_schema`, `test_monitor_role_reads_heartbeat_only`, `test_p5_dashboard_open_orders_query_uses_an_index`).
   - `rollback_analysis_role.sql` executed cleanly (`BEGIN`, `DO`, `COMMIT`).
2. **`P5` `EXPLAIN (ANALYZE, BUFFERS)` on seeded synthetic rows (500 `order`, 500 `order_intent`, 500 `approval`, 500 `ledger_entry`, 500 `trading_event`, 200 `reconciliation_run`, after `ANALYZE`, default planner settings):**
   - Open `LIVE` orders: `Index Scan using ix_order_origin_state on "order"` (`Execution Time: 0.038 ms`, `Buffers: shared hit=2`)
   - `AWAITING` approvals: `Index Scan using ix_trading_approval_state on approval` (`Execution Time: 0.019 ms`, `Buffers: shared hit=2`)
   - Recent 200 `order_intent`: `Index Scan Backward using ix_trading_order_intent_created_at on order_intent` (`Execution Time: 0.059 ms`, `Buffers: shared hit=6`)
   - Recent 100 `ledger_entry`: `Index Scan Backward using ix_trading_ledger_entry_at on ledger_entry` (`Execution Time: 0.049 ms`, `Buffers: shared hit=4`)
   - Recent 50 `trading_event`: `Index Scan Backward using ix_trading_trading_event_created_at on trading_event` (`Execution Time: 0.030 ms`, `Buffers: shared hit=4`)
   - Recent 10 `reconciliation_run`: `Index Scan Backward using ix_trading_reconciliation_run_started_at on reconciliation_run` (`Execution Time: 0.016 ms`, `Buffers: shared hit=2`)
3. **Restore rehearsal (`deploy/trader/rehearse_restore.sh`):**
   - `Restore rehearsal completed cleanly in 3s (scratch DB aidss_restore_rehearsal_1794712350 will now be dropped).`
   - 30 tables in `trading` restored; `rw_can_update_audit=f`, `rw_can_delete_audit=f`, `rw_can_update_ledger=f`, `monitor_can_select_lease=t`, `monitor_can_update_lease=f`, `monitor_can_select_cred=f`.
4. **Release checklist (`docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`):**
   - Updated with D2, D4, and `-m postgres` evidence; all owner-led items remain `[ ]`.

## What Was Not Done

- Host hardening on `10.1.200.13` (`isolate_analysis_role.sql`, port 5432 closure, superuser password rotation, owner-led restore drill) awaits the owner's SSH password and per-step gate approval.
