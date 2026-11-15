# 2026-11-15 — Task L: Repeatable Host-Hardening and Full-Dump Restore Rehearsal Scripts

## Scope and Changes

- Added [deploy/trader/rehearse_isolation.sh](../../deploy/trader/rehearse_isolation.sh):
  - Clones the source database into a temporary scratch database (`aidss_role_rehearsal_<ts>`), applies `deploy/trader/isolate_analysis_role.sql`, assigns a random temporary password to `aidss_app` via stdin (never via CLI arguments or `PGPASSWORD`), verifies role attributes (`rolsuper=f`, `rolcreatedb=f`, `rolcreaterole=f`, `rolbypassrls=f`), `public` table ownership, and `SET ROLE aidss_app` boundaries (`public` DDL succeeds; `SELECT 1 FROM trading.audit_log` denied), times `deploy/trader/rollback_analysis_role.sql`, and drops the scratch database (plus `aidss_app` if created by the script) in `trap cleanup EXIT INT TERM`.
- Updated [deploy/trader/rehearse_restore.sh](../../deploy/trader/rehearse_restore.sh):
  - Added `--full` flag to dump and restore the full database (`public` + `trading`), while keeping default `-n trading` behavior unchanged when called without `--full`.
- Added [tests/trader/test_rehearsal_scripts.py](../../tests/trader/test_rehearsal_scripts.py):
  - Static checks (no Docker required) verifying `set -eu`, `trap cleanup EXIT`, scratch DB & `aidss_app` cleanup, `--full` + `-n trading` support, and absence of literal passwords/secrets.
- Updated [docs/10-OPERATIONS/06-RUNBOOKS.md](../../docs/10-OPERATIONS/06-RUNBOOKS.md) (R13 and R14) to reference the two scripts.
- Left `isolate_analysis_role.sql` and `rollback_analysis_role.sql` untouched.

## Local PostgreSQL 18 Verification

- `rehearse_isolation.sh` (success run): `Clone completed in 2s`, `Isolation applied in 1s`, `aidss_app` `f/f/f/f`, `public_tables_not_owned_by_aidss_app = 0`, `SET ROLE aidss_app` verified (`public` DDL ok, `trading.audit_log` denied), `rollback` `1s`, `public_tables_not_owned_by_superuser = 0`, exit `0`.
- `rehearse_isolation.sh` (intentional failure against `nonexistent_db`): exited `1`, `trap cleanup` left zero `aidss_role_rehearsal_*` databases.
- `rehearse_restore.sh --full`: `public: 1`, `trading: 30` tables, `rw_can_update_audit=f`, `rw_can_delete_audit=f`, `rw_can_update_ledger=f`, `monitor_can_select_lease=t`, `monitor_can_update_lease=f`, `monitor_can_select_cred=f`, `Restore rehearsal completed cleanly in 4s`, exit `0`.
- `rehearse_restore.sh` (default `-n trading`): `trading: 30` tables, privilege checks passed, `Restore rehearsal completed cleanly in 4s`, exit `0`.

## Differences from VM Production

- Local rehearsal ran against `pgvector/pgvector:pg18` with a minimal `public.sample_analysis` table and empty `trading` tables, whereas the VM runs PostgreSQL 16 (`pgvector/pgvector:pg16`, ~337 MB `aidss` database).
- Neither script was run against the VM in Stage 4.
