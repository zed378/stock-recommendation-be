# 11 — Mode Promotion

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Risk Engineer, Technical Lead |
| **Decided by** | ADR-003, ADR-020 |
| **Open items** | OQ-12, OQ-16 |

Autonomy is earned with evidence (ADR-003). **No threshold below is set.** Each is an owner number (OQ-12),
and an unset threshold blocks promotion.

## Modes

`PAPER` -> `APPROVAL` -> `AUTO`. Demotion to any lower mode is always allowed, immediate, and needs no
evidence. A new `strategy_version` returns the strategy to `PAPER`.

## Gates: `PAPER` to `APPROVAL`

| Gate | Measure | Threshold |
|---|---|---|
| Backtest passes | Out-of-sample backtest, with the configured cost model, meets the owner's criteria | owner (OQ-12) |
| Paper duration | Continuous paper running time | at least four weeks (ADR-020) |
| Paper activity | Number of completed paper trades | owner minimum |
| Paper drawdown | Maximum drawdown in paper | within the owner's limit |
| Data integrity | No unresolved data gap or reconciliation-equivalent error during paper | zero |

## Gates: `APPROVAL` to `AUTO`

| Gate | Measure | Threshold |
|---|---|---|
| Live duration | Running time in `APPROVAL` with real capital | at least four weeks (ADR-020) |
| Capital | Live capital used during the period | within the owner's small-capital amount (OQ-16) |
| Reconciliation | Reconciliation runs with no unexplained difference | all |
| Kill switch | No unexplained kill-switch or breaker event | none |
| Slippage and fill quality | Live results against paper assumptions | within the owner's tolerance |
| Approval behavior | Fraction of intents the owner denied | reviewed by the owner |

"At least four weeks" is from the owner's answer (ADR-020). Every other number is the owner's to set.

## Evidence

Each gate's measured value, its threshold, the data range, and a pass or fail are stored in
`mode_change.evidence` (`03-DATA-MODEL/05`). The promotion screen shows them (`04-UX-UI/02`).

## Rules

1. Promotion is by `trade:promote`, never by an automated actor.
2. A failing or unset gate blocks promotion; there is no override.
3. Promotion is audited, with the evidence and the owner's note.
4. A **breaker trip** or **reconciliation difference** during `APPROVAL` or `AUTO` is recorded against the
   strategy; the owner decides on demotion. Automatic demotion on a breaker is a possible rule left to the
   owner.
5. **No strategy is promoted until the owner has set the thresholds.** Until then every strategy stays in
   `PAPER`.

## Why Gates Are Not Defaulted

A made-up threshold would let the system look as if a strategy had passed a test that nobody agreed to. The
owner sets them, once, before the evidence exists, so they cannot be chosen after seeing the result.
