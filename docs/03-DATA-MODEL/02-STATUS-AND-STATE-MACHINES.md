# 02 — Status and State Machines

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-003, ADR-024, ADR-026 |

Internal states keep the exchange's original status alongside (`exchange_status`), so a mapping bug cannot
hide what Indodax actually said.

## Order State Machine

| State | Meaning |
|---|---|
| `SUBMITTING` | Row written (write-ahead); the create request is about to be, or has been, sent |
| `UNKNOWN` | A create or cancel got a timeout or 5xx; the outcome is not known |
| `OPEN` | Accepted by Indodax, nothing filled (exchange `NEW`) |
| `PARTIALLY_FILLED` | Some quantity executed (exchange `PARTIALLY_FILLED`) |
| `FILLED` | Fully executed (exchange `FILLED`) |
| `CANCEL_REQUESTED` | A cancel was sent; not yet confirmed |
| `CANCELLED` | Cancelled (exchange `CANCELLED`). May carry `cancel_reason`, for example `SELF_TRADE_PREVENTION` |
| `REJECTED` | Refused (exchange `REJECTED`, or an error such as `-2010`) |

### Transitions

| From | To | Cause |
|---|---|---|
| (new) | `SUBMITTING` | Intent passed the Risk Engine; row persisted |
| `SUBMITTING` | `OPEN` | Create returned success |
| `SUBMITTING` | `REJECTED` | Create returned an error code |
| `SUBMITTING` | `UNKNOWN` | Timeout or 5xx on create |
| `UNKNOWN` | `OPEN`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED` | Query by `clientOrderId` found it |
| `UNKNOWN` | `REJECTED` (not found) | Only after 5 queries over 30 seconds (ADR-042), plus an alert; the pair stays held until the owner confirms |
| `OPEN` | `PARTIALLY_FILLED`, `FILLED` | Fill observed |
| `OPEN` or `PARTIALLY_FILLED` | `CANCEL_REQUESTED` | Timeout reprice, owner action, or kill switch |
| `CANCEL_REQUESTED` | `CANCELLED` | Confirmed |
| `CANCEL_REQUESTED` | `FILLED` | Filled before the cancel landed |
| `CANCEL_REQUESTED` | `UNKNOWN` | Cancel timed out |
| `PARTIALLY_FILLED` | `CANCELLED` | Remainder cancelled; the filled part stays |

No transition leaves `FILLED`, `CANCELLED`, or `REJECTED`. Every transition appends an `order_event`.

### Exchange Status Mapping

| Indodax | Internal |
|---|---|
| `NEW` | `OPEN` |
| `PARTIALLY_FILLED` | `PARTIALLY_FILLED` |
| `FILLED` | `FILLED` |
| `CANCELLED` | `CANCELLED` |
| `REJECTED` | `REJECTED` |
| WebSocket `FILL` (appears in the Private WebSocket docs only) | not used; WebSocket is deferred (ADR-011) |

An unrecognized status raises a reconciliation difference and halts; it is never guessed.

## Intent State Machine

`CREATED` -> `VETOED` | `RISK_REJECTED` | `AWAITING_APPROVAL` | `READY`

`AWAITING_APPROVAL` -> `APPROVED` | `DENIED` | `EXPIRED`; `APPROVED` and `READY` -> `ORDERED`.

`APPROVED` is valid only for the exact price and quantity shown; any change returns the intent to
`AWAITING_APPROVAL`. `PAPER` intents go `READY` -> `ORDERED` against the paper executor.

## Mode

`PAPER` -> `APPROVAL` -> `AUTO`, promotion by gates (ADR-020); demotion to any lower mode is always
allowed. A new `strategy_version` forces `PAPER`.

## Trading State (global)

| State | Meaning | Exit |
|---|---|---|
| `RUNNING` | Normal | n/a |
| `HALTED` | No new orders. Reason recorded | Explicit owner resume |
| `CANCELLING` | `CANCEL` in progress | Becomes `HALTED` |
| `FLATTENING` | `FLATTEN` in progress | Becomes `HALTED` |
| `DISABLED` | A required setting is missing, or the credential is unusable | Fixing the cause, then explicit resume |

There is **no automatic transition from any halted state back to `RUNNING`**.
