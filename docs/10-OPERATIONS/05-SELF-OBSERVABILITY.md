# 05 — Self-Observability

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-007 |
| **Open items** | OQ-26 (decided, ADR-039) |

## Logs

Structured JSON with a `correlation_id` per signal, intent, order, and fill, following the analysis
platform's logging convention. Redacted per `09-SECURITY-PRIVACY/05`. Never a key, signature, or balance.

## Metrics (proposed names)

| Area | Metrics |
|---|---|
| Liveness | Seconds since last completed cycle (strategy, exits, reconciliation); lease held; version |
| Exchange | Requests by endpoint and status; latency; error class counts; throttle waits; breaker state; clock skew |
| Data | Age of last price and last closed candle per pair; gaps |
| Orders | Orders by state; time in `UNKNOWN`; fills; rejects; STP cancellations |
| Risk | Each limit's used versus limit; breaker trips; kill-switch uses |
| Trading | Open positions; exposure; realized and unrealized PnL by origin (in the UI, not necessarily exported) |
| Reconciliation | Last run age; differences by kind |
| Context | Analysis context latency and availability; veto count |

## Health Endpoint

`GET /trader/v1/health` (authenticated) reports the above in structured form for the dashboard. A separate
unauthenticated liveness probe returns only up or down.

## The Watchdog Problem

The in-process watchdog (`05/09`) stops when the process stops, and so cannot report its own death. The
failure that matters most, **the Trader being down with positions open**, is exactly the one it cannot
announce. Therefore a **separate component outside the Trader's process** must alert on a stale heartbeat
(ADR-039). **A scheduled script on the host** reads the heartbeat from the database with a read-only role
(`trader_monitor`) and sends the alert **directly to Telegram**, without passing through the Trader. Its bot
token is a root-only file on the host, separate from the Trader's database. **Known gap:** if the host itself is
down, nothing alerts; the owner accepted this (ADR-039). An external heartbeat service remains a possible later
addition.

## Alerts

Defined in `05-MODULE-SPECIFICATIONS/12`. The ones that must never be silent: Trader or feed stalled,
`exit_unprotected`, breaker tripped, kill switch used, reconciliation difference, `UNKNOWN` order, permission
changed.

## Dashboards

The operator dashboard is the primary view (`04-UX-UI/01`). Infrastructure dashboards, if any, are in the
owner's existing monitoring; the Trader makes no assumption about which.

## Tracing a Trade

Given a `correlation_id`, an operator can follow signal, intent, risk checks, order, events, fills, ledger
entries, and audit rows. This is the main diagnostic tool.

## Tests (planned)

The liveness metric stops advancing when the loop is blocked; a stale heartbeat triggers the external check;
logs contain no sentinel secrets; the health endpoint distinguishes degraded from down.
