# 03 — Component Architecture

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-001, ADR-004, ADR-009, ADR-010 |

Proposed package layout under `src/aidss_trader/`:

```
connector/    market_data/   strategy/    intents/     risk/       orders/
exits/        killswitch/    ledger/      reconcile/   modes/      approval/
credentials/  notify/        analysis/    api/         audit/      config/
```

## Responsibilities and Dependencies

An arrow means "may import". Anything not listed is forbidden.

| Component | Responsibility | May depend on |
|---|---|---|
| `connector` | Sign and send Indodax requests; parse responses; normalize errors; throttle | `credentials`, `config` |
| `market_data` | Fetch and store candles, prices, pair metadata; compute freshness | `connector`, `ledger` (read DB only) |
| `strategy` | Pure: candles and parameters to signals | nothing (data in, data out) |
| `intents` | Signal to sized, quantized intent; reject intents without a stop | `strategy` outputs, `market_data` (read) |
| `analysis` | Fetch AI and Kronos context; return veto or none | HTTP client to the analysis platform only |
| `risk` | Pre-trade checks; circuit breakers; limit state | `ledger` (read), `config` |
| `orders` | State machine; persist-then-send; poll; cancel and reprice; resolve `UNKNOWN` | `connector`, `risk`, `ledger`, `audit` |
| `exits` | Stop and target monitoring; watchdog | `market_data`, `risk`, `orders` |
| `killswitch` | `HALT`, `CANCEL`, `FLATTEN` | `orders`, `ledger`, `audit` |
| `ledger` | Append-only fills; positions; WAC PnL | database only |
| `reconcile` | Compare with Indodax; trigger halt | `connector`, `ledger`, `killswitch`, `audit` |
| `modes` | Mode state; promotion gates | `ledger`, `audit` |
| `approval` | Approval queue | `intents`, `modes`, `audit` |
| `credentials` | Encrypt, store, test, rotate | database, `audit` |
| `notify` | Compose and send messages; redact | HTTP client to the channel |
| `api` | Operator API | all of the above through services, never raw tables |
| `audit` | Write audit rows | database only |
| `config` | Load limits and settings; report which are unset | database |

## Dependency Rules (each enforced by a test, `11-TESTING-QUALITY/01-UNIT-TESTS.md`)

1. **`strategy` imports nothing from the Trader.** It cannot reach the connector, orders, or database.
2. **Only `orders` and `killswitch` call order-mutating connector methods.** No other module may.
3. **`orders` calls `risk` before any create.** A create with no preceding risk result is a defect.
4. **`analysis` output has no field that `orders` or `intents` reads except `veto`.**
5. **`killswitch` does not import `strategy`, `intents`, `analysis`, or `approval`.** It must work when
   they are broken.
6. **No module imports `aidss`.** The Trader reaches the analysis platform over HTTP or a read-only view.
7. **`aidss` never imports `aidss_trader`.**
8. **No module outside `connector` contains a hostname or an Indodax path.**
9. **No module imports a withdrawal, deposit, or fiat method, because none exist.**

## The Emergency Path

`FLATTEN` and the stop exit use a `MARKET` order. They still pass through the Risk Engine, but through a
reduced **emergency profile** that checks only what must hold even in a crisis: the order reduces an
existing position, quantities respect increments and minimums, and rate limits hold. It does **not**
apply entry limits (daily loss, drawdown) that would otherwise block the very order that reduces risk.
`05-MODULE-SPECIFICATIONS/03-RISK-ENGINE.md` defines the profile.

## Circular Dependencies

None are allowed. `exits` depends on `orders`; `orders` does not know about `exits`. `reconcile` depends on
`killswitch`; `killswitch` does not know about `reconcile`.
