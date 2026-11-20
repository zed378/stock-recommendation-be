# T3-07 — Indodax IDR signal builder

## Request and analysis

Owner requested configurable signals combined with Kronos predictions and AI analysis
as a foundation for automated buying and selling. Existing systems include the isolated
Indodax Trader, a template strategy builder, a Binance signal worker and an AI reviewer.
Several status documents lag the code and recent ADR-065 to ADR-067 records. Recorded
deployments are historical evidence, not a fresh host inspection.

## Scope

Owner selected **Indodax spot IDR** after the initial offline SHADOW foundation.
The final local change adds a visual rule editor on Trader Strategies, persistent
audited strategy definitions, a pure `signal_builder` strategy, a separate opt-in
Kronos/AI worker, append-only review evidence and a required PAPER entry gate. See
`MEMORY/specs/T3-07-signal-decision-builder.md` (written before each implementation step).

## Architecture assessment

| Existing component | Reuse and gap |
|---|---|
| `aidss_trader.strategy` | Existing Decimal indicators and pure signal interface are reused by the new declarative strategy. Shared rules remain free of analysis imports. |
| `frontend/src/trader/StrategyBuilder.tsx` | Existing template editor remains; `SignalBuilder.tsx` adds declarative entry/exit groups and explicit stop/review numbers. |
| `aidss_signals.worker` | Daily screening and AI veto exist; it does not call Kronos or load the new definitions. |
| `aidss_signals.h4_pass` | Separate breakout/volume strategy pass exists; it is not the Trader's Indodax order loop. |
| `aidss.forecasting.service` | Kronos-base inference exists. Daily timestamps assumed a stock week; new explicit continuous-market flag fixes crypto callers while preserving old behavior. |
| Trader execution core | Risk, idempotent intents, order manager, exits, kill switch, reconciliation and promotion mechanisms exist. Their presence is not evidence of live readiness. No new bypass is introduced. |

The resulting decision flow for the standalone tool is: valid closed candles -> configured
entry rules -> Kronos provenance/return gate -> AI TAKE/score gate -> SHADOW candidate.
When already long: valid candles -> configured exit rules -> SHADOW EXIT or HOLD, without
model calls. Stops and kill-switch actions remain the existing independent controls.

The Indodax integration uses only stored `indodax_ohlc` data for explicitly named
IDR allowlisted pairs. Binance USDT output cannot supply a builder review here.
The model worker gets exact public-candle work through the Trader API, minimizing
its posted evidence to typed model context. The API independently derives pass/veto,
rechecks current work, then atomically records evidence and its hash-chain audit row.
No second DB audit writer is introduced. Review identity covers strategy id/version,
pair, timeframe, candle open and normalized data hash. Stale reviews and changed
inputs cannot release an entry. Model prose and projected prices supply no order field.

PAPER uses existing intent sizing, pair quantization, portfolio limits, ownership
and conservative fills. Matching model evidence never overrides missing limits.
Exits bypass reviews. Non-reference live promotion remains blocked by the existing
guard. Backtests carry `RULES_ONLY_NO_MODEL_REVIEWS`; they are not combined-model
performance evidence. Kronos crypto calendars include weekends, while stock callers
retain their existing default. The editor is scrollable with fixed action buttons.

## What Was Not Determined

No production migration, deployment, credential use, exchange request, real inference
or profitability claim is made. All model and exchange tests use synthetic doubles.
Owner numbers, CPU model provisioning, worker installation and readiness evidence
remain operator work. The current internal worker token needs existing operator
VIEW/CONFIGURE_STRATEGY privileges; narrower service credentials and review retention
remain open. ALL-only pairs receive no review and stay blocked. Definitions must
match the runtime timeframe; the current deployment defaults to 4H. Browser visual
QA could not connect: the in-app browser tool returned missing `sandboxPolicy`
metadata before setup. No browser or screenshot verification is claimed.

## Validation

- `python -m pytest tests/test_signal_builder.py tests/test_kronos_forecast.py
  tests/trader/test_guards.py tests/test_architecture_constraints.py -q`: **68 passed**
  for the initial offline foundation (prior to Indodax integration).
- Builder tests include `test_models_cannot_create_entry_and_exit_never_calls_models`,
  `test_kronos_and_ai_veto_cannot_be_removed`, `test_invalid_forecast_blocks_candidate`,
  `test_model_failure_blocks_candidate`,
  `test_unfinished_and_stale_data_block_before_models`,
  `test_any_group_with_missing_indicator_is_unavailable`,
  `test_crossovers_require_previous_side_and_strict_current_side`, and
  `test_crypto_daily_calendar_includes_weekends_and_stock_default_skips_them`.
- `tests/test_signal_builder.py`: **21 passed**, including CLI schema export,
  unrounded adapter prices, sample count and stale forecast source rejection.
  `python -m aidss_signals.builder --help` and `--schema`: succeed.
- `python -m ruff check src tests`: **passed**; `git diff --check`: passed
  (Git warns about repository CRLF conversion and its inaccessible global ignore file).
- Initial full hermetic attempt was interrupted after a setup error. The diagnostic
  `python -m pytest -q -x` reached **131 passed, 44 deselected, 1 error**: Windows
  sandbox denied `C:/Users/Zed/AppData/Local/Temp/pytest-of-Zed` for
  `test_a_coin_is_decided_once_per_daily_close_and_survives_a_restart`.
  Approved rerun outside the sandbox completed: **2715 passed, 1 skipped,
  44 deselected in 669.50 seconds**, exit 0. That run started before the final
  source-as-of/sample validation and two corresponding parameterized tests were
  added; the final changed code is covered by the subsequent **68 passed** targeted
  run above. No second full run is claimed for that last small change.

### Indodax integration verification

- `python -m pytest tests/trader/test_indodax_builder.py tests/test_signal_builder.py
  tests/trader/test_strategy_defs_api.py tests/trader/test_s2_multi_strategy.py
  tests/test_architecture_constraints.py -q -x`: **137 passed**.
- New tests: `test_paper_entry_requires_review_and_records_its_id`,
  `test_model_veto_and_source_mismatch_block_paper_entry`,
  `test_review_is_append_only_idempotent_and_audited`,
  `test_changed_candles_or_settings_cannot_reuse_review`,
  `test_expired_review_and_non_indodax_candles_block`,
  `test_exit_is_pure_and_does_not_need_a_review`,
  `test_review_routes_refuse_viewer_writes_and_missing_idempotency`,
  `test_worker_end_to_end_records_once_without_exchange_operations`, and
  `test_passing_models_cannot_override_unset_risk_limits`.
- `npm test -- --pool=vmThreads`: **162 passed**, all 23 files, after correcting
  test selectors for the accessible ID hint. Three new SignalBuilder component
  tests cover blank required values, exact serialized definitions and crossovers.
- `npm run build`: passed (`tsc -b` and Vite). `npm run lint`: exit 0, with the
  two existing `only-export-components` warnings in `primitives.tsx` (lines 20/28).
- OpenAPI regenerated from the local app; temporary JSON removed. Python lint passed.
- Full hermetic suite on the integrated code: **2731 passed, 1 failed, 1 skipped,
  44 deselected in 460.86 seconds**. The sole failure was
  `tests/trader/test_migration.py::test_upgrades_create_exactly_the_declared_tables`:
  its explicit chain still stopped at 0012. Added 0013 to that chain and its declared
  table union. `python -m pytest tests/trader/test_migration.py
  tests/trader/test_indodax_builder.py -q`: **18 passed** after the correction.
  No second full suite run is claimed after this test-only migration-chain correction.
- Migration 0013 upgrade was exercised against isolated SQLite through the migration
  test. PostgreSQL grants were not run against a real PostgreSQL server this session.
- `python -m aidss_signals.indodax_builder --help`: passed; no model or token was used.
