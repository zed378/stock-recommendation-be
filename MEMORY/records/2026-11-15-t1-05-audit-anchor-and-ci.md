# T1-05 External Audit Head-Hash Anchor & T1-02 CI Workflow

**Date:** 2026-11-15
**Tasks:** `T1-05`, `T1-02`
**ADR:** `ADR-054` (proposed)

## What Was Built

1. **External Audit Log Head-Hash Anchoring (`T1-05`, `ADR-054`):**
   - `src/aidss_trader/audit/log.py` & `src/aidss_trader/audit/__init__.py`: added `record_head_anchor(session, anchor_path)` and `verify_head_anchor(session, anchor_path)`.
     - `record_head_anchor` verifies the database chain (`verify_chain`), checks any previous external anchor against the database (raising `AuditChainBroken` on truncation or hash rewrite), and idempotently appends a JSONL entry (`seq`, `head_hash`, `anchored_at`) to `anchor_path` (`0600` best-effort) when the head advances.
     - `verify_head_anchor` verifies the database chain and confirms the latest external anchor matches the corresponding `AuditLog` row.
   - `src/aidss_trader/__main__.py`: added `audit-anchor --out <path> [--verify-only]` subcommand returning exit code `0` on success and `2` on `AuditChainBroken`.
   - `tests/trader/test_t1_leftovers.py`: added 3 hermetic unit tests (`test_external_head_anchor_records_and_is_idempotent`, `test_external_head_anchor_detects_db_truncation_or_rewrite`, `test_audit_anchor_cli`).

2. **GitHub Actions CI Workflow (`T1-02`):**
   - `.github/workflows/ci.yml`: added three jobs (`architecture-guard`, `trader-backend`, `frontend`):
     - `architecture-guard`: on `pull_request`, fails if `tests/test_architecture_constraints.py` is modified, and runs `pytest tests/test_architecture_constraints.py -q`.
     - `trader-backend`: installs `requirements-trader.lock` (`--require-hashes --no-deps`) + `pytest` + `ruff`, runs `ruff check src tests alembic_trader deploy` and `pytest tests/trader tests/test_frontend_routing.py -q`.
     - `frontend`: runs `npm ci`, `./node_modules/.bin/tsc -b --noEmit`, `npx oxlint .`, `npx vitest run --pool=vmThreads`, and `npm run build` in `frontend/`.

## Verification

- `.venv\Scripts\ruff.exe check src tests alembic_trader deploy`: **All checks passed!**
- `.venv\Scripts\python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q`: **518 passed, 7 deselected** (`-m postgres` deselected by default).

## What Was Not Determined / Remains Open

- **Owner confirmation for `ADR-054`:** host destination path (`--out`) and cron/timer schedule on `10.1.200.13` to run `audit-anchor` periodically outside the database.
- **GitHub Actions execution:** `.github/workflows/ci.yml` has not yet run on GitHub (not pushed).
- **Owner-gated / environment-gated items unchanged:** `T0-06` & `OQ-5`/`8`/`9`/`11`/`12`/`16` (owner numbers), `ADR-049` (per-pair overrides), `ADR-052` (`R5` frozen feed), `T2-07` & `T5-06` (live Indodax), `T6-03`/`T6-04` VM host execution (`isolate_analysis_role.sql`, `check_liveness.py` cron, restore drill).
