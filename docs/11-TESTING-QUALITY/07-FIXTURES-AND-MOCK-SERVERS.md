# 07 — Fixtures and Mock Servers

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer, Integration Engineer |
| **Decided by** | ADR-002 |
| **Open items** | OQ-18 (decided, ADR-038) |

Indodax has no sandbox, so the **mock exchange** is the substitute for the whole order path. It must be
trustworthy in what it claims and honest about what it does not model.

## Mock Exchange

A local HTTP server implementing the endpoints the connector uses (`06-INTEGRATIONS/04` to `08`) with
deterministic, scriptable behavior.

| Capability | Detail |
|---|---|
| Endpoints | Public: `/api/pairs`, `/api/price_increments`, `/api/server_time`, `/tradingview/history_v2`, `/api/v2/ticker/*`. Private: `/api/v2/account`, `order`, `openOrders`, `order/histories`, `myTrades` |
| Signature | Verifies HMAC-SHA256 over the transmitted string using **test-only** keys; reports why a signature failed (test mode only) |
| Time | Enforces `timestamp` and `recvWindow` against a controllable server clock |
| Order book | A simple matching model: `LIMIT` and `MARKET`, `GTC` and `MOC`, partial fills, STP modes |
| Idempotency | Rejects a duplicate `newClientOrderId` with `-2010` |
| Visibility lag | Optionally makes a just-accepted order invisible to `GET order` for a time, as the docs warn. **A required case:** a lag longer than the `UNKNOWN` window (30 s, ADR-042) must be tested, so the hold-and-alert path is exercised |
| Errors | Injects any documented code and HTTP status, 5xx, timeouts, truncated and malformed bodies |
| Rate limits | Enforces the documented limits, including per-pair create |
| Both forms | Can emit either documented form of a quirky field (`11` D9, D12, D17) |
| Account | Configurable balances and permission flags, including `canWithdraw` true |
| Pair state | Maintenance and suspension (`-1016`) |
| History windows | Enforces the 7-day cap and required `symbol` |
| Scripting | A scenario is a data file; a run is reproducible with a seed |

The mock **does not** model: real latency, real queue position, real fees (it uses configured values), the
exchange's actual matching and maintenance behavior, or any behavior the documentation does not state. Its
guarantees are about the Trader's handling, not about the exchange.

## Fixtures

| Rule | Detail |
|---|---|
| Synthetic by default | Shaped from the documentation, labelled synthetic with the page they came from |
| Recorded fixtures | Added only after the owner-led read-only verification (T2-07), redacted of credentials, `uid`, and balances, and labelled "recorded on <date>, <endpoint>" |
| No real keys | Not in fixtures, tests, logs, or the mock's config. Test keys are generated inside the test |
| **No Indodax sample keys** | Indodax's pages contain example keys and secrets; they are not copied |
| Versioned | A fixture records the documentation commit it was derived from (`8d1b409`) |
| Both forms | Fixtures exist for each accepted variant |

## Candle Fixtures

Synthetic series for entry, exit, flat, gap, and insufficient history cases, plus a longer recorded-shape
series for backtests. A backtest fixture is for testing the engine, not for judging a strategy.

## Analysis Context Fixtures

Typed responses (`08-AI-AGENT/06`): OK, partial, unavailable, stale, wrong candle, malformed.

## Fake Notification Channel

Records messages; never sends. Tests assert on content.

## Keeping the Mock Honest

When the live read-only verification shows a behavior that differs from the mock, the mock is corrected first
and a test is added that would have caught the difference. The mock's version is recorded in each test run.
