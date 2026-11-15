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
(ADR-039). **A scheduled script on the host** (`deploy/trader/check_liveness.py`) reads `trading.lease` from the
database with the read-only role (`trader_monitor`, granted `SELECT ON trading.lease` only) and sends the alert
**directly to Telegram**, without passing through the Trader:

- **Token file:** `/root/.aidss-monitor-telegram.env` (root-only, mode `0600` or `0400`), defining
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, separate from the Trader's database and never stored in the
  repository.
- **Threshold:** `15` seconds by default (`--max-age-s 15`, matching the ADR-043 lease TTL renewed every 5 s).
- **Cooldown:** `--state-file /var/run/aidss-trader-liveness.json --cooldown-s 300` prevents duplicate alerts
  within a 5-minute window while re-alerting if the Trader stays down, and clears automatically once a fresh
  heartbeat is observed.
- **Known gap:** if the host itself is down, nothing alerts; the owner accepted this (ADR-039). An external
  heartbeat service remains a possible later addition.

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

## Tests

The liveness metric stops advancing when the loop is blocked; a stale or missing heartbeat triggers the
out-of-process check (`tests/trader/test_liveness_monitor.py`, including `Acceptance A13` against a local fake
Telegram server); logs contain no sentinel secrets (`tests/trader/test_security_s1_s17.py`); the health endpoint
distinguishes degraded from down.
