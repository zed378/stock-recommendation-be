# Phase T4 — Execution Core

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T2 and T3 complete |
| **Exit criteria** | Risk Engine and breakers, the Order Manager with write-ahead and idempotency, lifecycle tracking, Exit Monitor and watchdog, the kill switch with a command-line tool, and the reconciler, **all verified on the mock exchange**; acceptance A1 to A3, A8 to A13, A17, A21 pass; resilience R1 to R11 pass |

**Needs from the owner:** OQ-9. The **mechanisms** can be built before the
values exist; the strategy stays disabled until they do.

**No real money in this phase.**

---

### T4-01 — Risk Engine and checks

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T3-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/03-RISK-ENGINE.md` |
| **Spec required** | yes |
| **Open numbers** | OQ-9 |

**Definition of Done**
- [ ] All ENTRY checks; EMERGENCY profile; fail-closed on an uncomputable check
- [ ] An unset required limit disables trading
- [ ] One test per check that **fails when the check is removed**; boundary tests
- [ ] A test that no module calls an order-mutating method without a prior `risk_check_result`

**Abuse cases**
- An override flag for "testing". There is none.
- Defaulting a limit.

### T4-02 — Circuit breakers

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-01 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/03` · `08` |
| **Spec required** | no |
| **Open numbers** | OQ-9 |

**Definition of Done**
- [ ] Daily loss, drawdown, consecutive losses; trip records values; configured tier
- [ ] No automatic resume; resume needs a note and is blocked while the cause persists
- [ ] Test `test_breaker_has_no_auto_resume`

### T4-03 — Order Manager: create, write-ahead, idempotency, `UNKNOWN`

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-06, T4-01 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/04-ORDER-MANAGER.md` · ADR-024, ADR-026 |
| **Spec required** | yes |
| **Open numbers** | none (ADR-035, ADR-042) |

**Definition of Done**
- [ ] Deterministic `clientOrderId`; row persisted and committed **before** the request; nothing sent if
      persisting fails
- [ ] A timeout or 5xx on create yields `UNKNOWN`, resolved by query; **never** a second create
- [ ] Integration I1 to I4
- [ ] Tests `test_client_order_id_is_pure_and_valid`, `test_timeout_is_resolved_by_query_not_retry`

**Abuse cases**
- Adding a retry "because it fixes flaky tests".
- Treating "not found" as "not placed" without the configured attempts and an owner confirmation.

### T4-04 — Lifecycle, partial fills, cancel and reprice

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/04` · `docs/03-DATA-MODEL/02` |
| **Spec required** | no |
| **Open numbers** | none (ADR-035, ADR-042) |

**Definition of Done**
- [ ] Polling, fills ingested once by `tradeId`, partial fills, cancel races (I8, I9)
- [ ] `MARKET` only on emergency paths (test `test_market_only_on_emergency_paths`)
- [ ] Test `test_every_state_transition`

### T4-05 — Exit Monitor and watchdog

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/09-EXIT-MONITOR.md` · ADR-007 |
| **Spec required** | yes |
| **Open numbers** | none (10 s poll and 3-cycle watchdog, ADR-041) |

**Definition of Done**
- [ ] Stop and target enforcement; one exit per position; stop never widened; stale price marks the position
      unprotected and alerts
- [ ] Restart evaluates stops first (I10); watchdog separate from the poller
- [ ] Performance P2 measured against the configured interval
- [ ] Tests `test_stop_crossing_emits_one_market_exit`, `test_watchdog_alerts_when_poller_stops`

**Abuse cases**
- Letting an analysis result delay a stop.

### T4-06 — Kill switch and the command-line tool

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/08-KILL-SWITCH.md` · ADR-010 |
| **Spec required** | yes |
| **Open numbers** | none (ADR-036) |

**Definition of Done**
- [ ] `HALT`, `CANCEL`, `FLATTEN`; idempotent, resumable, partial failure visible (I17, I18)
- [ ] **Independent of the Strategy Engine**: does not import `strategy`, `intents`, `analysis`, `approval`
- [ ] Emergency profile; reports dust and suspended pairs
- [ ] A minimal command-line tool on the host using the same code and audit
- [ ] Tests `test_kill_works_without_strategy_engine`, `test_unlisted_condition_cannot_flatten`

### T4-07 — Reconciler

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-03, T2-04 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/10-RECONCILIATION.md` · ADR-022 |
| **Spec required** | no |
| **Open numbers** | none (60 s, ADR-041) |

**Definition of Done**
- [ ] All comparisons and difference kinds; 7-day windows; a difference halts and is never auto-corrected
- [ ] Resolution via a reasoned `ADJUSTMENT` only
- [ ] Tests `test_difference_halts_and_does_not_autofix`; I6, I7
