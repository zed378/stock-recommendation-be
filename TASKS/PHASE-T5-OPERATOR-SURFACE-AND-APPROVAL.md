# Phase T5 — Operator Surface and `APPROVAL`

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T4 complete |
| **Exit criteria** | The owner can see state, approve or deny, promote or demote, and stop trading from the operator surface; notifications reach the phone; **and one strategy has run in `APPROVAL` with a small amount of real capital, with the release checklist for that stage fully checked** |

**Needs from the owner:** OQ-12, OQ-16, and the full set of risk numbers.

**This is the first phase that may touch real money, and only in T5-06.**

---

### T5-01 — Approval workflow and step-up authentication

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/07-APPROVAL-WORKFLOW.md` · `docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md` |
| **Spec required** | yes |
| **Open numbers** | none (1 hour, ADR-042) |

**Definition of Done**
- [ ] Approval bound to the exact intent hash; re-check at send time; expiry real; one decision per intent
- [ ] Step-up authentication for `FLATTEN`, `AUTO` promotion, limit increases, credential changes; mechanism
      recorded as an ADR
- [ ] Tests `test_approval_bound_to_exact_intent`; I19; S7, S9

**Abuse cases**
- A reusable approval token.

### T5-02 — Notifier and the chosen channel

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-02 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/12-NOTIFICATIONS.md` · `docs/06-INTEGRATIONS/12` |
| **Spec required** | yes |
| **Open numbers** | none (ADR-031) |

**Definition of Done**
- [ ] Events stored before sending; `CRITICAL` retried and acknowledged; cannot be silenced
- [ ] The channel is outbound only and never a control
- [ ] No key, signature, `uid`, balance, or total in any message
- [ ] Facts about the chosen service verified, not assumed
- [ ] Test `test_notification_has_no_secret_or_balance`; I21

### T5-03 — Mode promotion

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T3-04 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/11-MODE-PROMOTION.md` · ADR-020 |
| **Spec required** | yes |
| **Open numbers** | OQ-12 |

**Definition of Done**
- [ ] Gates computed from stored evidence; unset thresholds block; no override
- [ ] Promotion records evidence; demotion always allowed; a new version returns to `PAPER`
- [ ] Tests `test_promotion_requires_all_gates`; A14, A15

**Abuse cases**
- Choosing thresholds after seeing the results.

### T5-04 — Operator dashboard and controls

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-06, T4-07, T5-01 |
| **Spec refs** | `docs/04-UX-UI/00` to `03` · `docs/07-API-CONTRACTS/00`, `01` |
| **Spec required** | yes |
| **Open numbers** | none (ADR-033) |

**Definition of Done**
- [ ] State bar, positions, orders, risk usage, PnL by origin, approvals, events, kill switch on every page
- [ ] Freshness shown everywhere; unset shown as unset; paper and backtest labelled on the figure
- [ ] The Trader API enforces every permission; the OpenAPI enumeration test passes
- [ ] Accessibility for approve and kill controls; keyboard operable; confirmation for `CANCEL` and `FLATTEN`
- [ ] Types generated from OpenAPI, as the existing front end does
- [ ] Tests `test_dashboard_marks_stale_data`; S8, S16

### T5-05 — Export

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T5-04 |
| **Spec refs** | FR-T35 |
| **Spec required** | no |

**Definition of Done**
- [ ] CSV of ledger and audit for a range; row count equals the table's; exports are audited; no secrets
- [ ] Test `test_export_row_count_matches`

### T5-06 — Owner-led `APPROVAL` with small real capital

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T5-01 to T5-05, T6-04 (liveness check) recommended before |
| **Spec refs** | `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` · `docs/10-OPERATIONS/06-RUNBOOKS.md` |
| **Spec required** | yes |
| **Open numbers** | OQ-8, OQ-9, OQ-16 |
| **Owner-led** | **yes** |

**An agent prepares the checklist and stops.** The owner provides the key, sets every number, and decides.

**Definition of Done**
- [ ] The release checklist "Before the First `APPROVAL` With Real Money" is fully checked, each item with its
      evidence
- [ ] The key is Read plus Trade only; the start check passes
- [ ] Capital is the owner's stated small amount
- [ ] A kill-switch drill and a restore rehearsal are recorded
- [ ] The first live orders are observed and compared with the mock's assumptions; differences recorded
- [ ] A record names every test and states what is still not verified

**Abuse cases**
- Starting with a larger amount "because paper looked good".
- Skipping the kill-switch drill.
