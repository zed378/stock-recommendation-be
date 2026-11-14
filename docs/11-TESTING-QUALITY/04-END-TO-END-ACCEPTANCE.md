# 04 — End-to-End Acceptance

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |
| **Decided by** | ADR-003, ADR-010 |

Each acceptance scenario follows a use case (`01-PRODUCT-REQUIREMENTS/03`) through the real components, the
mock exchange, and the operator API. A scenario passes only when its named test passes; the record names them.

## Scenarios

| ID | Use case | Mode | Scenario | Pass condition |
|---|---|---|---|---|
| A1 | UC-T01 | any | Start with an unset limit | No orders; strategy disabled; the unset item named |
| A2 | UC-T01 | any | Start with a key that reports `canWithdraw` true | Refuses to trade; alerts |
| A3 | UC-T01 | any | Start with a skewed clock | Halts before a signed request |
| A4 | n/a | `PAPER` | Full loop: candle close, signal, intent, risk, paper fill, ledger, PnL | Zero signed order requests; paper figures labelled; no live PnL touched |
| A5 | UC-T02 | `APPROVAL` | Intent awaits approval; owner approves | One order created; bound to the intent hash |
| A6 | UC-T02 | `APPROVAL` | Owner denies; intent expires | No order; reasons recorded |
| A7 | UC-T02 | `APPROVAL` | Market moves after approval and the limit changes | Approval void; new approval required |
| A8 | n/a | `AUTO` | Valid entry; fill; position; stop crossed | One `MARKET` exit through the emergency profile; ledger and PnL correct |
| A9 | UC-T03 | any | Timeout on create | One request; `UNKNOWN`; resolved by query |
| A10 | UC-T04 | any | Daily-loss breaker trips | `HALTED`; no new entries; a stop still works; resume needs a note |
| A11 | UC-T05 | any | `HALT`, `CANCEL`, `FLATTEN` each from the API | Each step recorded; ends `HALTED`; `FLATTEN` closes positions |
| A12 | UC-T05 | any | Kill switch with the Strategy Engine stopped | All tiers still work |
| A13 | UC-T06 | any | Stop the Trader with an open position | The out-of-process check alerts; on restart stops are evaluated first |
| A14 | UC-T07 | any | Promote `PAPER` to `APPROVAL` with a failing gate | Refused; evidence shown |
| A15 | UC-T07 | any | Promote with an unset threshold | Refused; names the unset threshold |
| A16 | UC-T08 | any | Change a strategy parameter | New version; returns to `PAPER` |
| A17 | UC-T09 | any | Reconciliation difference | `HALT`; ledger not edited; resolved by `ADJUSTMENT` with reason |
| A18 | UC-T10 | any | Rotate the key | The new key is tested read-only and swapped atomically; no moment without a valid key |
| A19 | n/a | any | A veto rule fires on an entry | Entry blocked and recorded; an exit and stop unaffected |
| A20 | n/a | any | Context source unavailable | Entry proceeds by rules; absence recorded |
| A21 | n/a | any | Two Trader instances | Only the lease holder trades |
| A22 | n/a | any | Notification channel down | In-app event exists; `CRITICAL` retried |

## Acceptance for a Phase

A phase's exit criteria (`12-DELIVERY-PLAN/00`) list the scenarios that must pass. A scenario that cannot run
yet (for example one needing the operator surface) is stated as not run, not skipped silently.

## What Acceptance Does Not Show

It does not show that a strategy is profitable, that the exchange behaves exactly as the mock does, or that
the owner's limits are appropriate. The first is `PAPER` and `APPROVAL` evidence; the second is the
owner-led read-only live verification (T2-07); the third is the owner's judgement.
