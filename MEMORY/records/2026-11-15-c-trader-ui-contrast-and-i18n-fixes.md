# 2026-11-15 — Task C: Trader UI Contrast (WCAG AA) and Ledger Header Localization Fixes

## Scope

Task C of the Stage 2 Trader handoff: audit and fix all 7 Trader screens (`/trader`, `/trader/approvals`, `/trader/strategies`, `/trader/parameters`, `/trader/paper`, `/trader/limits`, `/trader/credentials`) plus `StateBar`, `KillControls`, and shared `trader/components.tsx`.

## What Was Found and Fixed

1. **WCAG AA contrast failure on `text-faint` across all Trader screens (`antislop-human` audit):**
   - `python contrast-check.py` against `frontend/src/index.css` proved `--color-faint` (`#5c6b7d`) has **3.53:1** contrast on `bg-surface` (`#0b0f14`) and **3.27:1** contrast on `bg-raised` (`#121821` inside `<Card>`), failing the WCAG AA 4.5:1 requirement for `text-xs`/`text-sm` readable text.
   - `--color-muted` (`#8b98a9`) has **6.55:1** contrast on `#0b0f14` and **6.08:1** on `#121821` (passes WCAG AA).
   - Replaced all 47 occurrences of `text-faint` on readable text across `frontend/src/pages/Trader.tsx`, `TraderApprovals.tsx`, `TraderStrategies.tsx`, `TraderParameters.tsx`, `TraderPaper.tsx`, `TraderLimits.tsx` (including `AllowlistForm` hints that previously delegated to `Field.hint`'s `text-faint`), `TraderCredentials.tsx`, `frontend/src/trader/StateBar.tsx`, and `frontend/src/trader/components.tsx` with `text-muted`.
2. **Hardcoded English table headers in `LedgerAndExportPanel` (`frontend/src/pages/Trader.tsx`):**
   - The 6 `<th>` headers (`At`, `Origin`, `Type`, `Asset`, `Amount`, `Reason`) in `LedgerAndExportPanel` were hardcoded in English even when `locale === "id"`.
   - Localized them to render `Waktu`, `Asal`, `Jenis`, `Aset`, `Jumlah`, `Alasan` when `locale === "id"` and `At`, `Origin`, `Type`, `Asset`, `Amount`, `Reason` when `locale === "en"`.
3. **Vitest + Testing Library coverage for all 7 Trader pages (`frontend/src/trader/__tests__/components.test.tsx`):**
   - Added test `renders all 7 Trader pages with populated tables in ID and EN, localizes ledger headers, and never uses low-contrast text-faint` rendering `<Trader />`, `<TraderApprovals />`, `<TraderStrategies />`, `<TraderParameters />`, `<TraderPaper />`, `<TraderLimits />`, and `<TraderCredentials />` in both `id` and `en` locales, verifying zero `.text-faint` elements, `overflow-x-auto` wrappers on wide tables, localized ledger headers, and `LIVE` / `PAPER` / `BACKTEST` origin badges.

## What Was Verified

- `python "C:/Users/Zed/.gemini/skills/antislop-human/contrast-check.py" '{"pairs":[{"fg":"#8b98a9","bg":"#0b0f14","size":"normal","context":"text-muted on bg-surface"},{"fg":"#8b98a9","bg":"#121821","size":"normal","context":"text-muted on bg-raised"}]}'` → `PASS` (`6.55:1` and `6.08:1`).
- `npx vitest run` in `frontend/`: **7 test files, 51 tests passed** (33 Trader tests across 4 files + 18 layout/sidebar/landing tests).
- `npm run typecheck`: 0 errors.
- `npm run lint`: 0 warnings, 0 errors.
- `npm run build`: succeeded (`dist/index.html` and bundles built).

## What Was Not Determined / Blocked

- Live Chrome DevTools automation against `https://aidss.zedth.my.id` was blocked in the local environment because the host Chrome browser did not have remote debugging enabled (`ENOENT: no such file or directory, open 'C:\Users\Zed\AppData\Local\Google\Chrome\User Data\DevToolsActivePort'`).
- Live deployment of the updated frontend bundle (`zed378/aidss-frontend:<sha>`) to `10.1.200.13` awaits the owner's SSH password (`infra@10.1.200.13`) and Task A deployment approval gate.
