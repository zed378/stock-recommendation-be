# 06 — Performance and Resilience Tests

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer, DevOps Engineer |
| **Decided by** | ADR-007, ADR-011 |
| **Open items** | OQ-6 (resolved, ADR-041 and ADR-043) |

Performance for this system means staying inside rate limits and reacting to stops in time. It does not mean
throughput. **Numeric pass thresholds depend on owner settings (ADR-041, ADR-043) and are not invented here**; each test
states what is compared with what.

## Performance

| ID | Test | Compares |
|---|---|---|
| P1 | Request budget | Measured requests per minute against the strictest applicable Indodax limit, for the configured allowlist size and intervals; must stay below with headroom (`02-ARCHITECTURE/08`) |
| P2 | Stop reaction | Time from a price crossing a stop in the mock to the `MARKET` request, against the configured polling interval plus a stated processing allowance |
| P3 | Kill switch | Time to complete each tier with N open orders and positions on the mock, respecting the cancel limit; recorded, and compared with the owner's tolerance |
| P4 | Reconciliation | Duration and request count per run for the configured pairs |
| P5 | Dashboard | Query plans for the dashboard use indexes; response time recorded |
| P6 | Candle ingest and backfill | Throughput within the legacy public limit (180 per minute) |

## Resilience (failure injection on the mock)

| ID | Injection | Expected |
|---|---|---|
| R1 | Exchange returns 5xx for a window | Connector breaker opens; no entries; the Exit Monitor keeps trying; `CRITICAL` after the configured time; recovery without manual steps except resume where required |
| R2 | Slow responses and timeouts | No duplicate orders; `UNKNOWN` handling; throttle respected |
| R3 | `-1003` bursts | Backoff; the cause is logged as a throttle defect |
| R4 | Truncated and malformed bodies | `MALFORMED`; nothing partially accepted |
| R5 | Price feed freezes | Stale marking; positions unprotected alert; entries blocked |
| R6 | Process crash at each step of order creation, cancel, kill switch, and fill ingestion | Restart recovers a consistent state with no duplicate and no lost order |
| R7 | Database restart mid-run | Trading halts; no order without a persisted row; recovery |
| R8 | Clock jumps forward and back | Skew detected; halt |
| R9 | Notification channel and analysis source fail | The order path is unaffected |
| R10 | Lease loss and takeover | Exactly one trader at a time |
| R11 | Disk full on logs | Logging failure does not stop stops or the kill switch |

## Soak

A long run in `PAPER` against a recorded series with periodic failure injection. Checks: no memory growth
beyond a stated bound, no lease flapping, no unbounded table growth beyond the retention plan, stable request
rate. The duration and bounds are set when the test is written.

## Chaos Safety

Failure injection runs only against the mock exchange and a test database. A test that could contact the real
exchange is a defect.

## Regression

R1 to R11 run in CI where feasible; the soak runs on a schedule. Results are recorded.
