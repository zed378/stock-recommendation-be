# 05 — Human Review and Audit

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer, Security Engineer |
| **Decided by** | ADR-003, ADR-004 |

## Human Review Points

| Point | Who | What they see |
|---|---|---|
| Approval of an entry in `APPROVAL` mode | Owner | The context, its age, and any veto, labelled as context |
| Enabling a veto rule for a strategy | Owner | The counterfactual evidence (`06`) |
| Promotion | Owner | Gates and measured values (`05/11`) |
| A vetoed intent | Owner (after the fact) | Which rule, values, thresholds; a list of vetoed intents is browsable |

In `AUTO` mode there is no per-order review. The review happens through the gates before promotion, the
limits, the events, and the daily reading of what was vetoed and why.

## Audit

Everything AI-related that touched a decision is stored and immutable:

| Stored | Where |
|---|---|
| Context received, with `generated_at`, `as_of`, model id, samples, platform record ids | `order_intent.analysis_context` |
| Veto rule, inputs, thresholds, outcome | `order_intent.veto` |
| Whether a veto rule was enabled at the time | In the strategy version snapshot on the intent |
| Enabling or disabling a veto rule | `audit_log` |

## Questions an Audit Must Be Able to Answer

1. Did any model output influence this order? (Only through a veto: the intent records it.)
2. If a veto was disabled, would it have fired? (The inputs are stored, so yes, it can be recomputed.)
3. What did the owner see when approving? (Context and age are stored with the approval.)

## What Is Not Audited Here

The internal reasoning of the analysis platform's agents. That is the analysis platform's own audit
(`conversations` and agent run records). The Trader stores a reference to them.
