# 04 — Functional Requirements

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Open items** | OQ-5, OQ-6 (resolved, ADR-041 and ADR-043), OQ-9, OQ-11, OQ-12, OQ-15 (resolved, ADR-041) |

Priority: **Must** = needed for the MVP; **Should** = valuable, may slip. Acceptance criteria are written to
be testable. Where a number is not decided it is written as `<setting>`; the open question is named.

## Market Data and Account

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T01 | Fetch candles for each allowlisted pair at 4H and 1D from `/tradingview/history_v2`, validate them, and store idempotently | Must | Re-ingesting a range inserts zero new rows; a malformed candle is rejected with a recorded reason |
| FR-T02 | Fetch last price and best bid/ask from the public ticker endpoints and record freshness | Must | Every price carries its source and fetch time; a price older than `<freshness_limit>` is marked stale |
| FR-T03 | Read pair metadata (increments, minimums, maintenance and suspension state) and refresh it | Must | An order below `trade_min_base_currency` or `trade_min_traded_currency` is never created |
| FR-T04 | Read account balances and permissions at start and at each reconciliation | Must | If `canWithdraw` or `canWithdrawFiat` is true, or `canTrade` is false, the Trader refuses to trade and alerts |

## Strategy and Intent

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T05 | A strategy turns candles into signals deterministically | Must | Same candles and parameters give byte-identical signals in two runs |
| FR-T06 | Provide the reference EMA plus ADX trend-following strategy with an ATR stop | Must | Parameters come from configuration (OQ-11); unit tests cover entry, exit, and no-signal cases on fixed fixtures |
| FR-T07 | Turn a signal into an order intent: size from risk percent, quantize, check minimums | Must | Quantity is rounded **down** to `quantity_increment`; an intent without a stop is rejected |
| FR-T08 | Every intent stores its reason, rule inputs and outputs, mode, and strategy version | Must | The intent row alone is enough to explain why it exists |
| FR-T09 | Attach AI and Kronos context to an intent; allow it to veto an entry | Should (post-MVP, ADR-032) | A veto blocks an entry and is recorded; a missing result does not block by default; no veto can create an order |

## Risk

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T10 | The Risk Engine checks every intent against the configured limits before any order exists | Must | Each limit has a test in which exceeding it rejects the intent with the limit's name |
| FR-T11 | A missing risk limit disables trading for the affected strategy | Must | Starting with an unset limit produces no orders and an alert |
| FR-T12 | A crossed circuit breaker halts trading, records which and the values, and requires an explicit owner resume | Must | No automatic resume exists in code |

## Orders

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T13 | Create `LIMIT` orders with a deterministic `newClientOrderId` | Must | The ID satisfies `[A-Za-z0-9_-]{1,36}` and is a pure function of the intent |
| FR-T14 | After a timeout or 5xx on create or cancel, resolve by querying `clientOrderId`; never re-send blindly | Must | A test injects a timeout and asserts exactly one create request |
| FR-T15 | Track order state by polling; handle partial fills, timeouts, and cancel-and-reprice | Must | Every transition in `03-DATA-MODEL/02` is covered by a test |
| FR-T16 | Use `MARKET` only for stop exits, `FLATTEN`, and other emergency liquidation | Must | A test asserts no entry or normal exit path can emit `MARKET` |
| FR-T17 | Throttle requests below Indodax limits and back off on `-1003` | Must | Under simulated load the client never exceeds its configured rate |
| FR-T18 | Compare server time with local time and refuse to trade beyond tolerance | Should | A simulated skew larger than `recvWindow` halts trading before a signed request is sent |

## Exits

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T19 | The Exit Monitor enforces stops and targets from the current price | Must | A price crossing a stop yields one `MARKET` exit intent through the Risk Engine's emergency path |
| FR-T20 | A watchdog detects a stalled Exit Monitor or price feed and raises a critical alert | Must | Stopping the poller triggers an alert within three missed poll cycles (ADR-041) |

## Modes and Approval

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T21 | Each strategy has exactly one mode; `PAPER` never contacts the order endpoint | Must | A test in `PAPER` asserts zero signed order requests |
| FR-T22 | `APPROVAL` mode: approve, deny, or expire an intent; approval is bound to that exact intent | Must | Changing price or size after approval requires a new approval |
| FR-T23 | Promotion between modes is gated by measurable evidence and audited; demotion is always allowed | Must | A promotion with a failing gate is rejected; thresholds come from configuration (OQ-12) |

## Kill Switch

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T24 | `HALT`, `CANCEL`, and `FLATTEN` can be triggered manually from the UI and the API, independent of the Strategy Engine | Must | With the Strategy Engine stopped, all three still work in tests |
| FR-T25 | Automatic triggers map to `HALT` or `CANCEL` as configured; no automatic trigger can `FLATTEN` (ADR-036) | Must | No automatic code path can request `FLATTEN` |

## Ledger and Reconciliation

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T26 | Maintain an append-only ledger of fills with fee, tax, and clearing recorded separately | Must | No update or delete is possible through the Trader's database role |
| FR-T27 | Reconcile orders, trades, and balances with Indodax at start and every 60 seconds (ADR-041); a difference halts trading | Must | An injected difference halts trading and alerts; the ledger is not auto-corrected |
| FR-T28 | Compute realized and unrealized PnL by weighted average cost; keep paper and live separate | Must | Paper and live PnL never sum in one figure |

## Backtest and Paper

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T29 | Backtest with a cost model (maker, taker, tax, clearing) and no look-ahead | Must | A test proves a decision at bar *t* cannot read bar *t+1* |
| FR-T30 | Simulate paper fills conservatively | Must | A `LIMIT` buy fills only if later price trades through it; rules in `05-MODULE-SPECIFICATIONS/06` |

## Operations

| ID | Requirement | Pri | Acceptance |
|---|---|---|---|
| FR-T31 | Credential admin: store encrypted, test read-only, rotate atomically, mask, audit | Must | The key is never returned by any API; rotation leaves no moment with no valid key |
| FR-T32 | Send the notification events in `05-MODULE-SPECIFICATIONS/12` to the in-app centre and the mobile channel | Must | Each event has a test; messages contain no key, signature, or full balance |
| FR-T33 | Write an audit row for every mutation: orders, mode, limits, kill switch, credentials, approvals | Must | The audit row names actor, action, before, after, and mode |
| FR-T34 | Operator dashboard: positions, open orders, PnL, limit usage, mode, data freshness | Must | Every figure shows its source and age; stale data is visibly stale |
| FR-T35 | Export the ledger and audit log as CSV | Should | Export row count equals the table's row count for the range |
