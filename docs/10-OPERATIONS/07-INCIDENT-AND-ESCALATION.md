# 07 — Incident and Escalation

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-015 |

With one owner there is nobody to escalate to inside the project. This document defines what counts as an
incident, what to do, and how to learn from it.

## Severity

| Level | Definition | Examples |
|---|---|---|
| **SEV1** | Money is at risk now or was lost through a system fault | Wrong or duplicate orders; suspected key compromise; positions unprotected during a fast move; a bypass of the Risk Engine |
| **SEV2** | Trading is stopped or degraded, no immediate loss | Breaker trip; reconciliation difference; Trader down with no positions |
| **SEV3** | Anything else that needs attention | A notification failure; a stale pair; a flaky endpoint |

## Response

1. **Stop the harm first.** `HALT`, `CANCEL`, or `FLATTEN` as the situation needs (`06-RUNBOOKS.md` R2).
2. **Preserve evidence.** Do not edit rows. Export the audit log and events for the period.
3. **Establish what happened** from the correlation ids, the order events, and the exchange history.
4. **Fix the cause**, not only the symptom.
5. **Resume deliberately** after reconciliation, with a note.

## Escalation Outside the System

| Situation | Action |
|---|---|
| Key compromise suspected | Revoke at Indodax at once; review account activity there |
| Exchange-side problem | Indodax's own support channels |
| Possible market-abuse concern (for example self-trades) | Read Indodax's terms and seek advice (OQ-1); this system gives no legal advice |
| Hosting or network failure | The host's operator (the owner) |

## Post-Incident Record

Every SEV1 and SEV2 gets a record in `MEMORY/records/` (`YYYY-MM-DD-incident-<slug>.md`) with: timeline,
impact in IDR where known, cause, what the system did and did not do, what was changed, and follow-ups added
to `TASKS/BACKLOG.md`. Records are not edited later to look better; a follow-up record is added instead.

If a limit, a gate, or a document turned out wrong, the deviation protocol applies (ADR, amend the document).

## Drills

Before the first live release and then at a cadence the owner sets: use each kill tier on the mock exchange;
simulate Trader down; simulate a reconciliation difference; restore from backup. A drill is recorded with its
result and time. A control that has never been exercised is assumed not to work.

## What an Incident Changes

A SEV1 pauses promotion. No strategy is promoted while a SEV1 from the last period is unresolved, and the
gates' "no unexplained event" criterion (`05/11`) is checked against the incident records.
