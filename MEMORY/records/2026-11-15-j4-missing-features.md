# Record — 2026-11-15 — Jalur 4: Backtest Persistence, Promotion Thresholds Editor, Origin-Separated Portfolio UI, CSV Export, and Per-Pair Parameters ADR

**Task ID:** Jalur 4 (`T4-05`, `T5-02`, `T5-03`, `T5-04` extensions)
**Role:** Trading Engineer / Frontend Developer
**Branch:** `main`
**Commit(s):** see git log for this commit

## Summary

Implemented the missing operator mechanisms for Jalur 4 while keeping all owner-decided numbers (`OQ-5`, `OQ-8`, `OQ-9`, `OQ-11`, `OQ-12`, `OQ-16`) strictly unset with zero defaults or suggestions:

1. **Backtest Persistence & Promotion Gate Evidence (`0007_backtest_runs`, `src/aidss_trader/backtest/engine.py`, `src/aidss_trader/promotion/gates.py`):**
   - Added additive table `trading.backtest_run` (`BacktestRunRow`, `origin="BACKTEST"`) and migration `alembic_trader/versions/0007_backtest_runs.py` (granting `SELECT, INSERT` to `trader_rw` on PostgreSQL).
   - Added `record_backtest()` (which persists `BacktestRunRow` and records a `backtest.recorded` audit row) and `latest_backtest_return_pct()`.
   - Wired `Promotion.gates()` so that when promoting `PAPER -> APPROVAL`, if `supplied.backtest_return_pct` is `None`, the gate automatically queries the latest stored `BacktestRunRow` matching `(strategy_id, row.version)`. A new strategy version automatically invalidates older backtest evidence (ADR-020).
2. **Promotion Thresholds Storage & Editor (`OQ-12`, `src/aidss_trader/runtime/settings_store.py`, `src/aidss_trader/api/app.py`, `frontend/src/pages/TraderStrategies.tsx`):**
   - Added `get_promotion_thresholds()`, `set_promotion_thresholds()`, `threshold_problem()`, and `thresholds_loosen()` in `settings_store.py`, wired into `build_api()` in `assembly.py` and `active_thresholds()` in `api/app.py`.
   - Added `GET /trader/v1/promotion-thresholds` (`perm.VIEW`) and `PUT /trader/v1/promotion-thresholds` (`perm.PROMOTE`, requires `Idempotency-Key`, requires `RAISE_LIMIT` step-up grant when loosening an existing threshold or setting a previously unset threshold, and writes an audit entry plus notification).
   - Built `<PromotionThresholdsCard />` and `<BacktestRunsCard />` (`<OriginBadge origin="BACKTEST" />`) on `/trader/strategies`.
3. **Origin-Separated Positions, PnL & Paper Equity + Generated API Response Types (`src/aidss_trader/api/app.py`, `frontend/src/api/trader-schema.d.ts`, `frontend/src/trader/types.ts`, `frontend/src/pages/Trader.tsx`, `frontend/src/pages/TraderPaper.tsx`):**
   - Added Pydantic `response_model` definitions across all JSON routes in `src/aidss_trader/api/app.py` and regenerated `frontend/src/api/trader-schema.d.ts` so `frontend/src/trader/types.ts` derives directly from `components["schemas"]`.
   - Added `GET /trader/v1/portfolio` (`perm.VIEW`) returning strictly separated `live` (`origin="LIVE"`), `paper` (`origin="PAPER"`), and `backtests` (`origin="BACKTEST"`) structures. Figures are never summed across origins.
   - Rendered `<PortfolioPanels />` on `/trader` and the `<OriginPortfolioBlock data={data.paper} />` card on `/trader/paper`, with `<OriginBadge />` attached to every figure and position row.
4. **Ledger & Audit CSV Export in UI (`frontend/src/pages/Trader.tsx`, `frontend/src/trader/mutations.ts`):**
   - Added `<LedgerAndExportPanel />` on `/trader` with download buttons for Ledger CSV (`kind=ledger`) and Audit CSV (`kind=audit`), verifying `X-Row-Count` against the downloaded CSV data rows.
5. **Per-Pair Strategy Parameter Overrides ADR (`MEMORY/DECISIONS.md`):**
   - Recorded `ADR-049` (`Status: proposed`) designing optional per-pair parameter overrides (`strategy_params:<strategy_id>:<pair>`) and version/mode reset rules without modifying the strategy implementation before the owner decides.

## Files Changed

- `src/aidss_trader/db/models.py` — added `BacktestRunRow` (`trading.backtest_run`).
- `alembic_trader/versions/0007_backtest_runs.py` — additive migration for `trading.backtest_run`.
- `tests/trader/test_migration.py` — included `0007_backtest_runs.py` in the migration drift test.
- `src/aidss_trader/backtest/engine.py`, `src/aidss_trader/backtest/__init__.py` — added `record_backtest` and `latest_backtest_return_pct`.
- `src/aidss_trader/promotion/gates.py` — automatic lookup of stored `BacktestRunRow` for `(strategy_id, row.version)` on `PAPER -> APPROVAL`.
- `src/aidss_trader/runtime/settings_store.py`, `src/aidss_trader/runtime/assembly.py` — added `get_promotion_thresholds`, `set_promotion_thresholds`, `threshold_problem`, `thresholds_loosen`.
- `src/aidss_trader/api/app.py` — added Pydantic `response_model`s for all JSON routes plus `GET/PUT /trader/v1/promotion-thresholds` and `GET /trader/v1/portfolio`.
- `frontend/src/api/trader-schema.d.ts`, `frontend/src/trader/types.ts` — regenerated OpenAPI schema and derived TypeScript response types from `components["schemas"]`.
- `frontend/src/trader/mutations.ts`, `frontend/src/trader/validators.ts`, `frontend/src/i18n/messages.ts` — added threshold mutations/validators, CSV export helper, and bilingual (`id`/`en`) copy.
- `frontend/src/pages/Trader.tsx`, `frontend/src/pages/TraderStrategies.tsx`, `frontend/src/pages/TraderPaper.tsx` — added origin-labelled portfolio panels, CSV export controls, backtest evidence table, and promotion threshold editor.
- `tests/trader/test_j4_features.py`, `frontend/src/trader/__tests__/validators.test.ts`, `frontend/src/trader/__tests__/components.test.tsx` — backend and frontend tests for Jalur 4.
- `MEMORY/DECISIONS.md` — added `ADR-049` (`proposed`).

## Decisions Referenced or Made

- **ADR-003, ADR-020:** Mode promotion gates and version reset on parameter change.
- **ADR-017:** Indonesian & English UI copy; English engineering documentation.
- **ADR-046:** `RAISE_LIMIT` step-up grant required when loosening promotion thresholds or unlocking a previously unset threshold.
- **ADR-049 (proposed):** Per-pair strategy parameter overrides and version tracking.

## Verification

- `python -m pytest tests/trader/test_j4_features.py tests/trader/test_migration.py tests/trader/test_t5_operator_surface.py` — passed.
- `ruff check` on all touched Python files — passed (`All checks passed!`).
- Frontend `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` — passed.

## What Was Not Determined

- Migration `0007_backtest_runs` has been tested in SQLite (`test_migration.py`, `test_j4_features.py`) but has **not** yet been applied to the production VM database (`10.1.200.13`), because we do not mutate the VM or deploy a new Trader image without the owner's instruction.
- `ADR-049` (per-pair strategy parameters) is `proposed` and awaits the owner's decision before any strategy code is changed.
