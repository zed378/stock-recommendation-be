# 03 — Use Cases

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-003, ADR-007, ADR-010, ADR-022 |

Actor is the Owner unless stated. Each journey names the requirements it exercises
(`04-FUNCTIONAL-REQUIREMENTS.md`).

## UC-T01 — Start the Trader safely

1. The Trader starts and loads configuration, strategies, and limits.
2. It checks that every required limit is set. A missing limit disables that strategy (FR-T11).
3. It reads the account and verifies `canTrade` is true and `canWithdraw` and `canWithdrawFiat` are false
   (FR-T04). Otherwise it refuses to trade and alerts.
4. It compares server time with local time (FR-T18) and reconciles open orders and balances (FR-T27).
5. Only if all pass does it begin evaluating strategies.

## UC-T02 — Review and approve an intent (`APPROVAL` mode)

1. A notification says an intent is waiting.
2. The Owner opens the approval queue and sees pair, side, price, quantity, stop, risk amount, the rule
   outputs, the AI and Kronos context, and the limits headroom.
3. The Owner approves or denies. An intent expires if not approved in time.
4. Approval is bound to that exact price and size; any change needs a new approval (FR-T22).

## UC-T03 — Investigate an order in state `UNKNOWN`

1. The Order Manager sent a create and got a timeout. It queries by `clientOrderId` (FR-T14).
2. If found, the order proceeds through its normal states. If not found after the configured attempts, an
   alert is raised and trading on that pair is held until resolved.
3. The Owner sees the timeline and the exchange's answers.

## UC-T04 — Respond to a circuit breaker

1. A limit is crossed, for example daily loss. The Risk Engine halts trading and records which limit and
   the values (FR-T12).
2. The Owner is notified, reviews, and either leaves the halt or resumes. Resume is an explicit, audited
   action and never automatic.

## UC-T05 — Press the kill switch

1. The Owner chooses `HALT`, `CANCEL`, or `FLATTEN` from the controls (FR-T24).
2. The Trader acts, reports each step's result, and stays halted until resumed.
3. `FLATTEN` shows expected positions and requires a deliberate confirmation.

## UC-T06 — The Trader or the price feed goes down

1. The watchdog detects a stalled component (FR-T20) and sends a critical mobile alert.
2. **Open positions have no stop while it is down** (ADR-007). The Owner decides whether to act at the
   exchange manually, following `10-OPERATIONS/06-RUNBOOKS.md`.

## UC-T07 — Promote a strategy

1. The Owner opens the promotion screen for a strategy in `PAPER`.
2. The system shows each gate, the measured value, and whether it passes (FR-T23).
3. Promotion is allowed only when every gate passes, and is recorded with the evidence.
4. Demotion to a lower mode is always allowed.

## UC-T08 — Evaluate a strategy change

1. The Owner changes a parameter. The strategy version increments and it returns to `PAPER`.
2. A backtest runs with the cost model (FR-T29) and results are stored against the version.

## UC-T09 — Handle a reconciliation difference

1. The Reconciler finds a difference (FR-T27). Trading halts and an alert shows what differs.
2. The Owner investigates, which may involve actions on the exchange outside the Trader.
3. After the cause is understood, the Owner records the finding and resumes. The ledger is **not**
   edited to match; a compensating entry with a reason is added (`05-POSITION-AND-LEDGER.md`).

## UC-T10 — Rotate the Indodax key

1. The Owner generates a new TAPIv2 key at Indodax and enters it in the credential screen.
2. The Trader tests it read-only (`GET /api/v2/account`), checks permissions, and swaps it atomically
   (FR-T31). The old key is revoked at Indodax by the Owner.
