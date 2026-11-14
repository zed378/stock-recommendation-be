# 01 — Unit Tests

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |

Pure logic, no network, no database. Every error branch is tested, not only the success path.

## Strategy Engine

- Determinism: two runs on a fixed fixture give identical serialized signals.
- Entry, exit, and no-signal cases for the reference strategy; insufficient history returns `NONE`.
- Only closed candles are inputs; passing an unfinished candle is rejected.
- No look-ahead: a decision at candle *t* cannot read *t+1*.

## Sizing and Intents

- Quantity rounds **down** to the increment; a property test checks that realized risk never exceeds
  `risk_amount`.
- An entry without a stop, or with entry at or below the stop, is rejected.
- Below the pair minimums produces `RISK_REJECTED` with `below_minimum`.
- Caps (`max_order_idr`, exposure) clamp correctly.
- All arithmetic is `Decimal`; a test fails if a `float` enters the sizing path.
- Intent identity is a pure function of its inputs; re-evaluating a candle cannot create a second intent.

## Risk Engine

- One test per check that **fails if the check is removed** (`00` principle 2).
- Each check's boundary: exactly at the limit, just under, just over.
- A check that cannot be computed fails.
- An unset required limit disables trading (`LIMIT_UNSET`).
- The emergency profile allows a reducing order while a breaker is tripped and rejects an increasing one.
- Breakers have no automatic resume.

## Order State Machine

- Every transition in `03-DATA-MODEL/02` succeeds; every non-listed transition is rejected.
- No transition leaves a terminal state.
- An unrecognized exchange status is rejected as `MALFORMED`.

## Idempotency Ids

- `clientOrderId` matches `[A-Za-z0-9_-]{1,36}`, is deterministic, and differs between distinct intents.

## Ledger and PnL

- Weighted average cost on buys, realized PnL on sells, costs as separate lines.
- A sell larger than the position raises `INTEGRITY`.
- Paper and live PnL never combine.
- An `ADJUSTMENT` without a reason is rejected.

## Exit Monitor

- A price crossing a stop yields exactly one exit; a stale price marks the position unprotected.
- A stop cannot be widened; stop takes precedence over target.

## Kill Switch (logic)

- Tier ordering; idempotence; resume after interruption; an unlisted automatic trigger cannot `FLATTEN`.

## Mode and Approval

- Promotion fails if any gate fails or its threshold is unset.
- Approval is bound to the exact intent hash; a changed intent voids it; a decided intent cannot be decided
  again.

## Dependency Rules

Import-graph tests enforce `02-ARCHITECTURE/03`: `strategy` imports nothing from the Trader; only `orders`
and `killswitch` call order-mutating connector methods; `killswitch` does not import `strategy`, `intents`,
`analysis`, or `approval`; no module imports `aidss`; no module outside `connector` holds a hostname or an
Indodax path.

## Redaction

Sentinel secrets fed to the logger, raw-response store, and notifier never appear in output.

## Quantization

Price and quantity helpers: increments, minimums, rounding direction, and values near the boundary.
