# T5 — Operator surface and APPROVAL: backend and front end built, unwired (in review)

**Date:** 2026-11-14
**Task:** T5-01, T5-02, T5-03, T5-05 built; T5-04 backend only; **T5-06 not started (owner-led)**
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/05-MODULE-SPECIFICATIONS/07`, `11`, `12`; `docs/06-INTEGRATIONS/12`; `docs/07-API-CONTRACTS/00`, `01`; ADR-020, 031, 033, 042, 046

---

## Hook

The approval, promotion, notification, export, and API logic exists and is tested on the mock, and a front end
for it now exists (see "Front end" below). **Nothing is wired and nothing was seen in a browser**: the Trader
process did not serve its API at the time (the runtime record changes this), and the screens were checked only
by type check, lint, build, and a check of the API's real response shapes. T5's exit criteria are **not met**.

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

## Front end (T5-04)

In `frontend/src/`: `trader/` (typed client, hooks, state bar, kill controls, step-up dialog), `pages/Trader.tsx`
(stop controls, open orders, limits, reconciliation, events), `TraderApprovals.tsx`, `TraderStrategies.tsx`
(promotion gates, demotion). The state bar and HALT sit in the sticky header on every page for the `trader` and
`admin` roles; CANCEL needs a confirmation naming the open-order count, FLATTEN needs the typed word plus a
step-up; unset limits show as unset; paper and live carry an origin label; every panel has loading, unavailable
(cause class and reference id), stale, and empty states; user-facing text is in both languages.

**Checked:** `tsc`, `oxlint`, `vite build` pass; the API's real responses were compared with `trader/types.ts`;
that comparison found and fixed padded decimals and offset-less timestamps (a browser would have read UTC as local).
**Not checked:** it was **never rendered or clicked in a browser**, no keyboard, screen-reader, or phone-width
check was done, and there are no front-end tests (the project has no runner). Types for request bodies are
generated (`python -m aidss_trader.api.openapi`, then `openapi-typescript`); response bodies are hand-declared
in `trader/types.ts` because the API has no response models. `schema.d.ts` was regenerated and differs by one
line (the `trader` role, which the analysis API already had).

## Not Done, Not Verified

- Front end gaps: ~~no limits or allowlist editor~~ (added, see below), ~~no strategy parameter editor~~ (added, see below), no paper-config editor, credential screen, PnL or position
  panels, export button, or realtime feed; the approval card lacks signal reasons, limit headroom, and costs
  because the API does not provide them. The nginx and Vite proxy to `trader:8001` are a plan, not a deployment.
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

## Limits and allowlist editor (added later)

`/trader/limits` edits the thirteen risk limits and the pair allowlist with its liquidity filter. No field has a
default or a suggestion; an empty field is unset and says trading is disabled. Every save goes through a review
that names what gets looser, tighter, cleared, or switched on, and a change that lets more risk through asks for
the password again (the screen mirrors the server's `loosens` rules; the server decides). The API now validates
ranges (percentages above 0 and at most 100, positive amounts and counts, a `HH:MM-HH:MM` window, only the
`LOCAL` day boundary) and the allowlist accepts any IDR pair, not only BTCIDR and ETHIDR (ADR-044 was a starting
list). **Not verified:** never rendered in a browser; no front-end tests; the client-side mirror of the server's
rules is hand-kept and could drift. All pairs share one strategy parameter set; per-pair parameters do not exist.

## Strategy parameter editor (added later)

`/trader/parameters` edits the seven EMA-ADX numbers. No field has a default or a suggestion and every field must
be filled. Saving different numbers creates a new strategy version and returns the strategy to PAPER; the screen
says so before saving, with more force when the strategy is live, and unchanged numbers are not a new version. The
API gained `GET /strategies/{id}/parameters`, and now refuses an ADX threshold outside 0 to 100 and periods that
need more candle history than the 300 the runtime keeps (such a strategy would sit silently inert). **Not
verified:** never rendered in a browser, no front-end tests, and the client-side checks are a hand-kept mirror of
the server's. Parameters are shared by every pair on the allowlist.
