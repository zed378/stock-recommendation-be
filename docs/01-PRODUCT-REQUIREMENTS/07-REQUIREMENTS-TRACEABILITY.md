# 07 — Requirements Traceability

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |

Links each requirement to its module spec, API, planned test, and delivery task. **Every test named here
is planned; none exists yet.** The column heading says so on purpose: a name in this table is not
evidence until `TASKS/PROGRESS.md` and a record say it passed.

Test names use the `tests/trader/` prefix. Task IDs are in `../../TASKS/`.

| FR | Module spec | API (`07-API-CONTRACTS/01`) | Planned test | Task |
|---|---|---|---|---|
| FR-T01 | `03-DATA-MODEL/03`, `06-INTEGRATIONS/05` | internal | `test_candles_ingest_is_idempotent` | T2-03 |
| FR-T02 | `06-INTEGRATIONS/05` | `GET /health` freshness | `test_stale_price_is_marked_stale` | T2-03 |
| FR-T03 | `06-INTEGRATIONS/05` | internal | `test_order_below_minimum_is_not_created` | T2-03 |
| FR-T04 | `06-INTEGRATIONS/07` | `GET /status` | `test_withdraw_permission_blocks_start` | T2-04 |
| FR-T05 | `05/01` | none | `test_strategy_is_deterministic` | T3-01 |
| FR-T06 | `05/01` | none | `test_ema_adx_entry_exit_fixtures` | T3-02 |
| FR-T07 | `05/02` | none | `test_sizing_rounds_down_and_requires_stop` | T3-03 |
| FR-T08 | `05/02` | `GET /intents/{id}` | `test_intent_explains_itself` | T3-03 |
| FR-T09 | `08-AI-AGENT/02` | `GET /intents/{id}` | `test_veto_blocks_but_never_creates` | T3-05 |
| FR-T10 | `05/03` | none | `test_each_limit_rejects_when_exceeded` | T4-01 |
| FR-T11 | `05/03` | `GET /status` | `test_missing_limit_disables_strategy` | T4-01 |
| FR-T12 | `05/03` | `POST /resume` | `test_breaker_has_no_auto_resume` | T4-02 |
| FR-T13 | `05/04`, `06/06` | internal | `test_client_order_id_is_pure_and_valid` | T4-03 |
| FR-T14 | `05/04` | internal | `test_timeout_is_resolved_by_query_not_retry` | T4-03 |
| FR-T15 | `05/04`, `03/02` | `GET /orders` | `test_every_state_transition` | T4-04 |
| FR-T16 | `05/04` | none | `test_market_only_on_emergency_paths` | T4-04 |
| FR-T17 | `06/08` | none | `test_client_never_exceeds_rate` | T2-05 |
| FR-T18 | `06/04` | `GET /status` | `test_clock_skew_halts_before_signing` | T2-05 |
| FR-T19 | `05/09` | none | `test_stop_crossing_emits_one_market_exit` | T4-05 |
| FR-T20 | `05/09` | `GET /health` | `test_watchdog_alerts_when_poller_stops` | T4-05 |
| FR-T21 | `05/06` | `GET /strategies` | `test_paper_mode_sends_no_order_request` | T3-04 |
| FR-T22 | `05/07` | `POST /intents/{id}/approve` | `test_approval_bound_to_exact_intent` | T5-01 |
| FR-T23 | `05/11` | `POST /strategies/{id}/promote` | `test_promotion_requires_all_gates` | T5-03 |
| FR-T24 | `05/08` | `POST /kill` | `test_kill_works_without_strategy_engine` | T4-06 |
| FR-T25 | `05/08` | none | `test_unlisted_condition_cannot_flatten` | T4-06 |
| FR-T26 | `05/05`, `03/04` | `GET /ledger` | `test_ledger_role_cannot_update_or_delete` | T1-03 |
| FR-T27 | `05/10` | `GET /reconciliation` | `test_difference_halts_and_does_not_autofix` | T4-07 |
| FR-T28 | `05/05` | `GET /pnl` | `test_paper_and_live_pnl_never_sum` | T3-04 |
| FR-T29 | `05/06` | none | `test_backtest_has_no_lookahead` | T3-04 |
| FR-T30 | `05/06` | none | `test_paper_limit_fills_only_if_traded_through` | T3-04 |
| FR-T31 | `05/13` | `PUT /credentials` | `test_key_is_never_returned` | T1-04 |
| FR-T32 | `05/12` | none | `test_notification_has_no_secret_or_balance` | T5-02 |
| FR-T33 | `09/04` | `GET /audit` | `test_every_mutation_writes_audit` | T1-05 |
| FR-T34 | `04-UX-UI/01` | `GET /dashboard` | `test_dashboard_marks_stale_data` | T5-04 |
| FR-T35 | `05/05` | `GET /export` | `test_export_row_count_matches` | T5-05 |

`05/NN` abbreviates `05-MODULE-SPECIFICATIONS/NN-*`; `06/NN` abbreviates `06-INTEGRATIONS/NN-*`.
