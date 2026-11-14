# 03 — Integration Tests

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |
| **Decided by** | ADR-022, ADR-026, ADR-027 |

Components together, with PostgreSQL (for roles, privileges, and column-level grants) and the mock
exchange. Marked `postgres` where the dialect matters.

## Scenarios

| # | Scenario | Asserts |
|---|---|---|
| I1 | **Write-ahead.** Kill the process after the order row is committed and before the response | On restart the order is `UNKNOWN`, resolved by querying `clientOrderId`, and exactly one order exists at the mock |
| I2 | **Persist failure.** The database is unavailable at the write-ahead step | No create request reaches the mock |
| I3 | **Timeout on create.** The mock accepts but the response is delayed | One create request; resolved by query; no duplicate |
| I4 | **Duplicate `clientOrderId`.** The mock returns `-2010` | The order becomes `REJECTED`; no retry with a new id |
| I5 | **Single instance.** Two Trader processes start | Exactly one holds the lease and trades; the other idles; after the holder dies the other takes over only after expiry |
| I6 | **Reconciliation difference.** The mock holds an order the Trader did not place | `ORDER_MISSING_LOCALLY`, `HALT`, no auto-adoption |
| I7 | **Permission change.** The mock reports `canWithdraw` true | `HALT`, `CRITICAL`, no orders |
| I8 | **Partial fills.** The mock fills in pieces | Ledger and position follow; fills ingested once each; stop and size follow the executed quantity |
| I9 | **Cancel races a fill.** Fill lands before the cancel | `CANCEL_REQUESTED` to `FILLED`; no phantom cancel |
| I10 | **Restart with a position through its stop.** | The Exit Monitor evaluates stops before anything else and exits once |
| I11 | **Stale price.** The mock stops updating prices | Position marked unprotected, `CRITICAL`; entries blocked |
| I12 | **Clock skew.** The mock enforces `recvWindow` and the test skews the clock | `HALT` before a signed request is sent |
| I13 | **Rate limit.** The mock enforces its limits under load | The throttle keeps requests under them; no `-1003` |
| I14 | **Privileges.** Connect as `trader_rw` | `UPDATE` and `DELETE` fail on append-only tables; only the listed `order` columns can be updated; no write outside `trading` |
| I15 | **Cross-role.** Connect as the analysis role | No write on `trading` |
| I16 | **Migration drift.** Build an empty database from migrations | Matches the models exactly |
| I17 | **Kill switch.** Each tier with open orders and positions | Each step recorded; ends `HALTED`; the Strategy Engine stopped does not matter |
| I18 | **Kill switch partial failure.** One cancel fails | The rest proceed; the report lists what remains |
| I19 | **Approval staleness.** Reprice after approval | The approval is void; a new one is required |
| I20 | **Analysis unavailable.** The context source times out | Rules proceed; the absence is recorded |
| I21 | **Notification failure.** The channel is down | The in-app event exists; `CRITICAL` retried |
| I22 | **Credential unreadable.** Wrong master key | `DISABLED`; no orders; alert |

## Data

Scenarios use scripted mock behavior and fixed clocks. Each records its seed so a failure reproduces.

## Boundaries Covered

B3 (database roles), B4 (exchange connection), B5 (analysis interface), B6 (notification) from
`09-SECURITY-PRIVACY/03`.
