# 00 — Product Vision

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead, with the Owner |
| **Decided by** | ADR-001, ADR-003, ADR-004, ADR-012 |

## What the Trader Is

An autonomous spot-trading service for a small, owner-chosen set of IDR pairs on Indodax. It watches
4-hour and daily candles, applies deterministic strategies, and places limit orders within hard risk
limits. It earns autonomy in stages and can be stopped in one action at three levels of severity.

## The Problem

The owner wants to trade crypto on a swing horizon without monitoring the market all day, but does not
want an opaque bot with access to real funds. Existing tools either execute without inspectable limits
or require constant manual action.

## Who Operates It

One owner. The same person approves orders, sets every risk number, and decides when a strategy has earned
more autonomy.

## What Success Looks Like

Outcomes the design is built to make **checkable**, not promises about returns:

| Outcome | How it is checked |
|---|---|
| No order is ever sent that violates a configured limit | Risk Engine tests; every order row links to the checks it passed |
| The local ledger and Indodax never disagree silently | Reconciliation runs; a difference halts trading and alerts |
| The owner can stop everything quickly | Kill switch drill in `10-OPERATIONS/06-RUNBOOKS.md`, with a recorded time |
| No strategy trades live money without evidence | Promotion gates (ADR-020) with the evidence stored |
| Funds cannot be withdrawn by the Trader | No withdrawal code; startup refuses a key with withdrawal permission |
| Every decision can be explained afterwards | Each intent stores its inputs, rule outputs, and the AI context it saw |

## What It Deliberately Is Not

- Not a source of trading advice. The analysis platform produces analysis; the Trader executes rules the
  owner has approved.
- Not a high-frequency or scalping system (ADR-012).
- Not multi-user or multi-account (ADR-015).
- Not a replacement for the owner's judgement on legality, tax, and how much to risk.

## A Plain Statement of Risk

Automated trading of volatile assets can lose all the capital allocated to it. Backtests and paper results
do not predict live results. While the Trader or its price feed is down, open positions have no stop
(ADR-007). These documents reduce operational risk; they do not remove market risk.
