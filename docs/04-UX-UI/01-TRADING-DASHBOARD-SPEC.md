# 01 — Trading Dashboard Spec

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer (frontend) |
| **Decided by** | ADR-003, ADR-007 |
| **Open items** | OQ-14 (resolved, ADR-028) |

Satisfies FR-T34. Data comes from the Trader's API (`../07-API-CONTRACTS/01-TRADER-API.md`).

## Layout (top to bottom)

### 1. State Bar (always visible)

| Element | Source | Notes |
|---|---|---|
| Trading state | `GET /status` | `RUNNING`, `HALTED` (with reason), `CANCELLING`, `FLATTENING`, `DISABLED` |
| Kill switch control | n/a | `HALT`, `CANCEL`, `FLATTEN` (`02`) |
| Lease | `GET /status` | Holder and heartbeat age. "No active Trader" is shown plainly |
| Exchange connector | `GET /health` | OK, degraded, or open breaker, with last success time |
| Clock skew | `GET /health` | Measured offset against Indodax server time |
| Last reconciliation | `GET /reconciliation` | Time and result. A difference is red and links to it |
| Key permission check | `GET /status` | `canTrade` true, `canWithdraw` false: confirmed at time |

### 2. Strategies

One card per strategy: name and version, **mode** (`PAPER`, `APPROVAL`, `AUTO`) as a labelled badge, pairs,
last signal, open position count, and whether it is disabled because a limit is unset (names which).
Promotion and demotion are launched from here (`02`).

### 3. Positions

Per pair: quantity, average cost, last price **with age**, unrealized PnL, stop and target, distance to
stop, and whether the Exit Monitor is currently healthy for it. A position whose price feed is stale shows
a critical marker, because it is effectively unprotected (ADR-007).

### 4. Open Orders

Pair, side, type, price, quantity, executed, state, age, `clientOrderId`. An `UNKNOWN` order is highlighted
with the time it has been unresolved.

### 5. Risk Usage

Each configured limit as used versus limit: daily loss, drawdown, consecutive losses, open positions,
per-pair and total exposure. A limit that is **unset** is shown as unset, not as zero.

### 6. PnL

Realized and unrealized, **live and paper in separate blocks** with their labels. Fee, tax, and clearing
shown as separate lines. No combined total across origins.

### 7. Approval Queue Summary

Count of intents awaiting approval, oldest first, linking to `02`.

### 8. Event Feed

Recent trading events (`../02-ARCHITECTURE/06-EVENT-AND-ALERT-FLOW.md`). `CRITICAL` events stay until
acknowledged.

## Freshness Rules

Every number shows its age. Beyond the freshness limit the element is marked stale and its value is greyed
with the age shown; the UI never displays a stale value as if it were current.

## Refresh

REST for initial load and reconnect; the in-app event feed uses the platform's existing realtime channel
where available. If the realtime channel drops, the page says so and falls back to periodic refresh; it never
silently stops updating.

## What Is Not Here

No candlestick chart in the MVP (the analysis platform already has price charts), no manual order ticket
(there is no manual order entry: orders come from strategies, and `FLATTEN` is the only manual market
action), and no leaderboard or performance gamification.
