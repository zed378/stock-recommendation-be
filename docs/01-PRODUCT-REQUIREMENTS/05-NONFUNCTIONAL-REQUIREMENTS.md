# 05 — Non-Functional Requirements

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Open items** | OQ-6 (resolved, ADR-041 and ADR-043), OQ-15 (resolved, ADR-041), OQ-20 (decided, ADR-040) |

Where a value is not decided, the requirement states the property and names the open question; it does
not make up a number.

| ID | Area | Requirement |
|---|---|---|
| NFR-T01 | Correctness | Money and quantities are `Decimal`; no `float` reaches the ledger or an order payload (ADR-025) |
| NFR-T02 | Safety | Uncertain state halts trading. Stale data, an `UNKNOWN` order, clock skew, a reconciliation difference, and an unreadable credential each halt |
| NFR-T03 | Restart safety | After a crash or restart the Trader recovers state from its database and the exchange, and never re-creates an order that already exists |
| NFR-T04 | Idempotency | A create is identified by `clientOrderId`; replays cannot duplicate (ADR-024) |
| NFR-T05 | Exit latency | Time from a stop being crossed to a `MARKET` exit being sent is bounded by the Exit Monitor's polling interval plus processing; the interval is 10 seconds (ADR-041) |
| NFR-T06 | Freshness | Every price, balance, and position shown or used carries its source and age; use of data older than the configured limit is blocked |
| NFR-T07 | Rate limits | Client-side throttling stays below Indodax limits (C4, C5 in `00-PROJECT-CONTEXT/04`) with headroom |
| NFR-T08 | Time | Signed requests use a timestamp within `recvWindow`; the server clock is disciplined by NTP and monitored |
| NFR-T09 | Auditability | Every order, decision, mode change, limit change, and credential change is attributable to an actor and time, and cannot be edited |
| NFR-T10 | Security | Keys are encrypted at rest with a dedicated master key, never logged, never returned by an API (ADR-014) |
| NFR-T11 | Availability | The Trader may be down; the design assumes it will be. The consequence of downtime is bounded by exposure limits (ADR-007, ADR-009) and the watchdog alert |
| NFR-T12 | Recoverability | The `trading` schema is backed up and a restore is rehearsed; RPO and RTO targets are the owner's (backups are manual, ADR-040) |
| NFR-T13 | Isolation | The analysis platform's role cannot write the `trading` schema; the Trader's role cannot write outside it (ADR-021) |
| NFR-T14 | Resource use | CPU only. Kronos is never in the order path and never blocks it (ADR-004) |
| NFR-T15 | Observability | Structured logs with a correlation id per intent and order; metrics for request rate, errors, latency, reconciliation result, limit usage, mode |
| NFR-T16 | Testability | The whole order path runs against a mock exchange without network access; no test calls production Indodax |
| NFR-T17 | Determinism | Strategy output depends only on its inputs and parameters |
| NFR-T18 | Accessibility | The operator UI meets the platform's existing accessibility baseline; destructive controls need a deliberate confirmation, not a single accidental click |
| NFR-T19 | Maintainability | Trading code stays in `aidss_trader` with a documented, tested boundary to `aidss` (ADR-001) |
