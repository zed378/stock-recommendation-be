# T5 — Operator surface and APPROVAL: backend built, UI not built (in review)

**Date:** 2026-11-14
**Task:** T5-01, T5-02, T5-03, T5-05 built; T5-04 backend only; **T5-06 not started (owner-led)**
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/05-MODULE-SPECIFICATIONS/07`, `11`, `12`; `docs/06-INTEGRATIONS/12`; `docs/07-API-CONTRACTS/00`, `01`; ADR-020, 031, 033, 042, 046

---

## Hook

The approval, promotion, notification, export, and API logic exists and is tested on the mock. **There is no
user interface**, so the owner cannot yet approve, promote, or stop trading from a screen, and nothing is
wired into the run loop, so no intent is ever created for approval. T5's exit criteria are **not met**.

---

## What Changed

| Task | Detail |
|---|---|
| T5-01 | `approvals/`: approval bound to a hash of pair, side, price, quantity, stop (normalised so a database round trip does not change it); one decision per intent; 1-hour expiry; risk re-check at send time with no retry; no automated actor. `auth/stepup.py`: single-use 5-minute grants after password re-entry (ADR-046, **proposed**) |
| T5-02 | `notify/`: event stored before delivery; CRITICAL retried with backoff, cannot be silenced or collapsed, stays unacknowledged; payload keys that look like a secret or a balance are refused; Telegram channel outbound only |
| T5-03 | `promotion/`: gates from stored evidence where it exists; every owner threshold unset by default and blocking; one step at a time; AUTO needs a step-up; demotion always allowed; a new version returns to PAPER |
| T5-04 (API) | `api/`: `/trader/v1` with a permission on every route, idempotency keys, confirmation text for CANCEL and FLATTEN, step-up for FLATTEN, AUTO promotion, and loosening a limit; `/kill` needs only the kill switch |
| T5-05 | `export/`: CSV of ledger and audit for a range, audited, formula cells neutralised |
| Data | Migration `0004_operator_surface`: `strategy`, `mode_change`, `approval`, `trading_event`, `step_up_grant` with column-level grants (PostgreSQL grants **not run**) |

## Telegram: verified and not verified

Read in `core.telegram.org/bots/api` and `/bots/faq` on 2026-11-14: the method URL form, the `ok` /
`description` / `error_code` response shape, and the advice of about one message per second to one chat.
**Not verified:** whether a bot can message a user who never pressed Start (assume the owner must), the
maximum text length (messages are capped at 400 characters by the notifier and truncated at 4000 by the
channel), and the exact `retry_after` shape. No live call was made.

## Not Done, Not Verified

- **T5-04 front end** (state bar, approvals queue, promotion screen, kill controls, accessibility,
  generated types). None of it exists.
- **Not wired:** nothing creates an `OrderIntentRow` or calls `ApprovalWorkflow.request` from a running
  strategy; `ApiContext` has no production assembly (`submit_approved`, `thresholds`, `freshness`); the API is
  not served by `aidss_trader run`. Credentials routes (`/credentials`), `/allowlist`, strategy parameter
  edits, and `/reconciliation/{id}/resolve` are not built.
- Idempotency keys are required but not stored, so a repeated key is not deduplicated; the approval and
  kill paths are idempotent by their own design, a promotion or limit change is not.
- Promotion evidence for backtest, paper drawdown, live capital, slippage, and denial fraction is supplied
  by the caller; the platform does not store it yet.
- ADR-046 is `proposed`; the owner has not confirmed password re-entry as the step-up mechanism.
- PostgreSQL grants for migration 0004 and the Telegram channel against the real service are unverified.
- T5-06 has not been started and must not be by an agent. Its checklist status is in
  `TASKS/PROGRESS.md`.
