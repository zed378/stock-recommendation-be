# Task S: Sync Accepted ADR-046, 047, 049, 051 Across Docs and Backlog

**Date:** 2026-11-16
**Task:** S (Stage 10)

## What Was Changed

1. [`TASKS/BACKLOG.md`](../../TASKS/BACKLOG.md):
   - Updated the `ADR-049` row from `proposed` (awaiting owner choice) to `accepted (owner, 2026-11-16)`: a single parameter set applies to all pairs; per-pair override design is not adopted (reopen only if owner requests).
   - Updated the `ADR-051` row from `proposed` (awaiting cleanup job) to `accepted (owner, 2026-11-16)` and recorded the actual implementation: opportunistic pruning (`_Replays._prune_expired` in `src/aidss_trader/api/app.py`) deletes expired (>24h) rows in its own transaction after `put()`, tested in `tests/trader/test_d_gaps.py` (`test_put_prunes_expired_rows_but_keeps_fresh_rows`, `test_pruning_failure_does_not_fail_put_or_request`), not yet run on VM PostgreSQL 16.
   - Left `ADR-052` (`proposed`) open as instructed.
2. [`TASKS/PROGRESS.md`](../../TASKS/PROGRESS.md):
   - Updated the `T3` row to state `ADR-049 accepted (owner, 2026-11-16): single parameter set for all pairs; per-pair override design not adopted`.
3. [`docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md`](../../docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md):
   - Updated `## Step-Up for High-Impact Actions` from `(proposed)` / "mechanism and window are undecided" to `(ADR-046, accepted (owner, 2026-11-16))` documenting the single-use 5-minute password re-entry grant.

Historical `MEMORY/records/` and `MEMORY/handoffs/` entries were intentionally left untouched. `CLAUDE.md` had no stale `proposed` or undecided claims for ADR-046, 047, 049, or 051.

## Verification

- `.venv\Scripts\python.exe -m pytest tests/test_frontend_routing.py tests/test_architecture_constraints.py -q`: `42 passed in 9.28s`.
