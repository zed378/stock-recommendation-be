# 04 — Evidence and Hallucination Controls

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-004 |

The strongest control is architectural: **no model output reaches an order path**. The rest limit what the
model's output can do to the owner's view and to a veto.

## Controls

| # | Control | Effect |
|---|---|---|
| 1 | Typed context only | The Trader reads a closed label, numbers, and enums; never free text |
| 2 | Numbers are computed, not generated | Prices, sizes, stops, and targets come from deterministic code. A model number is never used as one |
| 3 | Veto-only authority | A hallucinated or injected result can cause a missed trade, never an order |
| 4 | Schema validation | Context that does not match the schema is discarded as unavailable |
| 5 | Provenance stored | Each context carries model id, sample count, as-of time, and the platform's record ids |
| 6 | Freshness check | Stale or mismatched-candle context is ignored |
| 7 | Evidence for the owner | The approval card shows the context's source and age, so the owner can weigh it |
| 8 | No account data to models | There is nothing sensitive to leak or to be conditioned on |
| 9 | Counterfactual evaluation | A veto is enabled only if it improved out-of-sample results (`06`) |

## What the Trader Does Not Try to Detect

It does not attempt to judge whether a model's narrative is true. It does not need to: the narrative is never
an input. The platform's own agents have their own validation (schema checks, calibration, an execution
language guard), which the Trader neither relies on nor weakens.

## Prompt Injection

News and social text processed by the analysis platform can contain instructions aimed at the model. The
Trader's exposure is bounded by control 3: the only consequence is a spurious veto. That residual effect is
accepted and monitored (the rate of vetoes per strategy is a metric).

## Spurious Veto as a Signal

A sudden jump in veto frequency is a data-quality or injection signal. It raises a `WARN` event, because
silently trading less is also a failure mode worth knowing about.
