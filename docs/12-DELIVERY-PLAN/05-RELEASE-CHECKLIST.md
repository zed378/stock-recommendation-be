# 05 — Release Checklist

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead, Risk Engineer |
| **Decided by** | ADR-003, ADR-020 |

Each item is checked with evidence (a named test, a record, or an owner statement). An unchecked item blocks
the stage named in its heading. Checklists are filled in the release record.

## Before Any Live Read-Only Contact (T2-07)

- [ ] The owner has generated a **Read-only** TAPIv2 key and provided it for the check, by a means that
      avoids the repository and chat history.
- [ ] The connector's allowlist guard passes (no write method reachable from the check).
- [ ] The `live_readonly` run is explicit and confirmed; it logs no secret.
- [ ] Differences found are recorded in `06-INTEGRATIONS/11` and the mock corrected.

## Before the First `APPROVAL` With Real Money (T5-06)

**Code and tests**
- [ ] All guard tests pass (`11/00`), by name, in the record.
- [ ] The analysis platform's architecture test passes unmodified.
- [ ] Contract, integration, acceptance A1 to A22, and security S1 to S17 pass on the mock.
- [ ] Resilience R1 to R11 pass.
- [ ] Image scan, secret scan, and a check that the image has no torch, no tests, no secrets, and no configuration values.
- [ ] The Trader image repository is **private** (ADR-030). Copies pulled while it was public are assumed seen, so no secret or owner number was ever in them.

**Controls**
- [ ] Every risk limit is **set by the owner** and recorded (OQ-9). None is a default.
- [ ] The kill switch has been drilled on the mock, from the UI, the API, and the command line.
- [ ] The key is **Read plus Trade only**; the start check confirms `canWithdraw` and `canWithdrawFiat` false.
- [ ] The master key is in its decided custody and a re-entry procedure has been rehearsed (ADR-029).
- [ ] A restore of the `trading` schema has been rehearsed, with its time recorded (ADR-040).
- [ ] The out-of-process liveness check alerts on a stopped Trader (ADR-039).
- [ ] The notification channel is chosen, tested, and carries no secret or balance (ADR-031).
- [ ] An independent review of the operator API, credential flow, and kill switch is recorded.

**Process**
- [ ] The strategy has met the `PAPER` to `APPROVAL` gates with thresholds the owner set in advance (OQ-12).
- [ ] Initial live capital is the owner's stated small amount (OQ-16).
- [ ] The owner has read the threat model's accepted residual risks and the runbooks.

## Before Considering `AUTO`

- [ ] At least four weeks in `APPROVAL` with real capital (ADR-020).
- [ ] Reconciliation runs clean across that period, with no unexplained difference.
- [ ] No unexplained kill-switch or breaker event; incident records reviewed.
- [ ] Live fill quality compared with paper assumptions, within the owner's tolerance.
- [ ] The owner has set and met the thresholds in advance, and records the decision to promote.
- [ ] A fresh threat-model review.

## After Each Release

- [ ] The running image digest equals the intended tag.
- [ ] Reconciliation is clean; health and clock skew are normal.
- [ ] The owner resumed trading explicitly.
- [ ] The release record is written and `TASKS/PROGRESS.md` updated.
