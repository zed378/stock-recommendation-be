# Phase T6 — Hardening and Release

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T5 complete (T6-04 should land before T5-06) |
| **Exit criteria** | Security tests and an independent review recorded; resilience and soak tests pass; runbooks drilled and restore rehearsed; an out-of-process liveness check alerts on a stopped Trader; the release checklist and the `AUTO` readiness review are complete |

**Decided:** OQ-1 (ADR-037), OQ-20 (ADR-040), OQ-26 (ADR-039). Nothing blocks T6.

**Note on ordering:** T6-04 (liveness) and T6-03 (drills, restore) are prerequisites for responsible live use,
so they are scheduled **before** T5-06 even though they sit in this phase. The phase rule is read as "do not
start T5-06 until these specific T6 tasks are done".

---

### T6-01 — Security tests and independent review

| | |
|---|---|
| **Status** | PARTIAL 2026-11-15: S1 to S17 written (25 pass, S13 pinning xfail, S15 role clause diverges); **the independent review is not done** |
| **Depends on** | T5-04 |
| **Spec refs** | `docs/11-TESTING-QUALITY/05-SECURITY-TESTS.md` · `docs/09-SECURITY-PRIVACY/00-THREAT-MODEL.md` |
| **Spec required** | no |
| **Owner-led** | yes (choosing the reviewer) |

**Definition of Done**
- [ ] S1 to S17 pass, by name
- [ ] An independent review of the operator API, credential flow, and kill switch is recorded with findings
      and fixes
- [ ] The threat model is revisited against what was built

### T6-02 — Resilience and soak tests

| | |
|---|---|
| **Status** | REVIEW 2026-11-15: R1 to R11, P1 to P4, P6 and a PAPER soak pass on the mock; P5 not done; soak is simulated time only |
| **Depends on** | T4 complete |
| **Spec refs** | `docs/11-TESTING-QUALITY/06-PERFORMANCE-AND-RESILIENCE-TESTS.md` |
| **Spec required** | no |
| **Open numbers** | none (ADR-041) |

**Definition of Done**
- [ ] R1 to R11 pass; P1 to P6 recorded against the configured values
- [ ] A soak run in `PAPER` with failure injection; bounds stated and met

### T6-03 — Runbook drills and restore rehearsal

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T4-06, T4-07 |
| **Spec refs** | `docs/10-OPERATIONS/04` · `06` · `07` |
| **Spec required** | no |
| **Open numbers** | none (ADR-040) |
| **Owner-led** | yes |

**Definition of Done**
- [ ] Each kill tier drilled on the mock; Trader-down simulated; a reconciliation difference simulated
- [ ] A restore of the `trading` schema into scratch and into place, with timing recorded
- [ ] The master-key re-entry procedure rehearsed (ADR-029)
- [ ] Drills recorded in `MEMORY/records/`; runbooks corrected where they were wrong

**Abuse cases**
- Marking a drill done without running it.

### T6-04 — Out-of-process liveness check

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-07 |
| **Spec refs** | `docs/10-OPERATIONS/05-SELF-OBSERVABILITY.md` · ADR-039 |
| **Spec required** | yes |
| **Open numbers** | none (ADR-039) |

**Definition of Done**
- [ ] A scheduled host script alerts to Telegram, directly and independently of the Trader, when the heartbeat is stale
- [ ] Acceptance A13 passes
- [ ] The read-only role `trader_monitor`, the root-only token file, and the host-down gap are documented and rehearsed

### T6-05 — Release checklist and the `AUTO` readiness review

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T5-06 and the `APPROVAL` period |
| **Spec refs** | `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` · ADR-020 |
| **Spec required** | no |
| **Owner-led** | **yes** |

**Definition of Done**
- [ ] The "Before Considering `AUTO`" checklist, each item with evidence
- [ ] The owner's thresholds were set before the evidence was gathered
- [ ] Incident records reviewed; no unexplained kill-switch or breaker event
- [ ] A fresh threat-model review
- [ ] The decision to promote or not is the owner's and is recorded either way

**Abuse cases**
- Treating "four weeks passed" as sufficient without the other gates.
