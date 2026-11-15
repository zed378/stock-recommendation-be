# 2026-11-15 — T5-04 frontend test suite and UI parity audit

**Tasks:** T5-04 (`TASKS/PHASE-T5-APPROVAL-MODE.md`)
**Status:** `REVIEW` (Vitest + Testing Library suite passes; live browser click-through on `https://aidss.zedth.my.id` awaits a `trader`/`admin` test account from the owner)

## Context

The Trader frontend (`frontend/src/trader/` and `frontend/src/pages/Trader*.tsx`) previously had no test
runner (`typecheck`, `lint`, and `build` only). Track 2 required:
1. Adding a frontend test runner (Vitest + Testing Library + jsdom) and writing unit and component tests
   for `format.ts`, `limitsMeta.ts`, strategy parameter and paper assumption validators, write-only
   credential inputs, the `FLATTEN` confirmation and step-up flow, `StateBar`, `OriginBadge`, and error/stale
   states.
2. Auditing client-side loosening and validation logic against `limit_problem`, `loosens`, `allowlist_loosens`,
   and `paper_flatters` in `src/aidss_trader/api/app.py` and `src/aidss_trader/runtime/settings_store.py`.
3. Inspecting all seven Trader screens (`/trader`, `/trader/approvals`, `/trader/strategies`,
   `/trader/parameters`, `/trader/paper`, `/trader/limits`, `/trader/credentials`) for accessibility,
   responsive layout, bilingual (`id`/`en`) parity, and antislop compliance.

## What Was Done

- **Frontend test runner (`frontend/package.json`, `frontend/vite.config.ts`):**
  - Added `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`,
    and `jsdom`, configured under `"test": "vitest run"`.
- **Extracted pure validators & server-parity helpers (`frontend/src/trader/limitsMeta.ts`, `frontend/src/trader/validators.ts`):**
  - Added `limitsLoosen`, `PAIR`, `parsePairs`, `allowlistLoosens`, and `allowlistEffects` to
    `limitsMeta.ts`.
  - Extracted `PARAM_FIELDS`, `paramProblem`, `emaOrderBad`, `neededHistory`, `PAPER_FIELDS`,
    `paperProblem`, `paperEffect`, and `paperFlatters` into `validators.ts` (preserving
    `react/only-export-components` in `.tsx` files).
- **Defects found and fixed:**
  1. `frontend/src/pages/TraderLimits.tsx` (`AllowlistForm`): when `max_spread_pct` failed validation
     (outside `(0, 100]`), the form previously rendered `trader.limits.invalid.number` ("Must be a number
     above 0") instead of `trader.limits.invalid.pct` ("Must be above 0 and at most 100"). Fixed to render
     the distinct percentage range message.
  2. `frontend/src/pages/TraderLimits.tsx` (`AllowlistForm` review dialog): the three `ReviewLine` rows in
     the allowlist review modal previously hardcoded `effect="neutral"` even when a pair was added or
     `minVolume`/`maxSpread` was loosened or tightened. Wired `allowlistEffects` so each row displays its
     true `looser`/`tighter`/`enabled`/`cleared` badge.
- **Test suite (`frontend/src/trader/__tests__/`):**
  - `format.test.ts` (8 tests): `multiplyDecimals`, `compareDecimals`, `groupDigits` (`id` and `en`),
    `ageSeconds`.
  - `limitsMeta.test.ts` (11 tests): `problem`, `effect`, `needsStepUp`, `limitsLoosen`, `allowlistLoosens`,
    `allowlistEffects`, `parsePairs`, `PAIR`.
  - `validators.test.ts` (4 tests): `paramProblem`, `emaOrderBad`, `neededHistory`, `paperProblem`,
    `paperEffect`, `paperFlatters`.
  - `components.test.tsx` (5 tests): `id`/`en` key parity and em-dash absence across all `trader.*` keys;
    `KillControls` `FLATTEN` word confirmation + `StepUpDialog` + `Escape` close; `TraderCredentials`
    write-only password fields cleared on refusal/submission; `StateBar` role gating (`trader`/`admin` vs
    `investor`) and `HALT` availability during `UNAVAILABLE` errors; `OriginBadge`, `TraderErrorNote`, and
    `PanelBody` stale/unavailable rendering.

## Verification

- `npm test` in `frontend/`: **4 test files, 28 tests passed**.
- `npm run typecheck`, `npm run lint`, `npm run build` in `frontend/`: **0 warnings, 0 errors**.
- `ruff check src/aidss_trader tests/trader alembic_trader`: **All checks passed**.

## What Was Not Determined

- **Live browser click-through on `https://aidss.zedth.my.id`:** Chrome DevTools remote debugging was not
  active on the workstation (`DevToolsActivePort` absent) and a `trader`/`admin` test account on production
  has not yet been provided by the owner (registering accounts on production without permission is forbidden).
