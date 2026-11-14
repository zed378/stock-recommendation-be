# 03 — Release and Rollback

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-007, ADR-021 |

A release restarts the Trader. **While it is stopped, open positions have no stop** (ADR-007). A release is
therefore an operational event with a procedure, not a routine push.

## Before Releasing

1. All gates pass: lint, typecheck, hermetic tests, migration drift check, the analysis platform's
   architecture test, image scan, secret scan.
2. The record and `TASKS/PROGRESS.md` are updated in the same commit.
3. The release is checked against `12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`.
4. Prefer a time with **no open positions** and no pending approvals. If positions are open, the owner is
   told that stops are unmonitored for the restart window and accepts it.

## Procedure

| Step | Action | Check |
|---|---|---|
| 1 | Take a backup of the `trading` schema | Restorable (`04`) |
| 2 | `HALT` (so nothing is created mid-restart) | State shows `HALTED` |
| 3 | Run additive migrations as `trader_owner` | Drift check clean |
| 4 | Deploy the new immutable image tag | Running digest equals the intended tag |
| 5 | The Trader starts, acquires the lease, loads state, **evaluates stops first**, reconciles | Reconciliation clean |
| 6 | Verify health, clock skew, credential test, key permissions | All OK |
| 7 | The owner **resumes** explicitly | State shows `RUNNING` |
| 8 | Watch the first cycles | No alerts |

The Trader does **not** resume on its own after a release.

## Rollback

| Aspect | Rule |
|---|---|
| Image | Redeploy the previous immutable tag. Migrations are additive, so the previous code runs against the newer schema |
| Schema | Not rolled back against a database holding live records (`03-DATA-MODEL/07`). A destructive migration is never part of a normal release |
| State | After rollback, reconcile before resuming |
| Decision | The owner decides to roll back; `HALT` first |

If a release changed behavior that affected orders, the owner reviews orders placed since the release before
resuming.

## Feature Flags

New behavior that touches orders ships **disabled by default**, enabled by an audited setting, and a new
strategy always starts in `PAPER`.

## Versioning

Commit-based tags on the image; a human-readable version in the dashboard footer so the running version is
visible. The deployed digest is recorded in the release record.

## What a Release Never Does

Change a limit, promote a mode, alter a credential, or resume trading.
