# 02 — Veto Rules

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-004 |
| **Open items** | OQ-13 (decided, ADR-032), OQ-25 (deferred by decision, ADR-045) |

A veto is a deterministic rule over typed context fields. It blocks an **entry**. Nothing else.

## Rule Shapes

No threshold is set here; each is an owner setting, set at the post-MVP evidence review (ADR-045) and an unset threshold means that rule never
vetoes (so an unset value cannot make the system trade differently than it would without AI).

| Rule | Shape |
|---|---|
| Kronos bearish | `kronos.direction_bias == bearish` **and** `kronos.projected_return_pct <= -kronos_veto_return` |
| Analysis stance opposed | `analysis.label` is in the configured opposed set **and** `analysis.confidence >= analysis_veto_confidence` |
| Both required | Optional strategy setting: veto only if both rules above hold |

## Properties

1. **Entry only.** A veto never applies to an exit, a stop, `FLATTEN`, or a cancel.
2. **Blocks, never creates.** There is no rule of the form "if context is bullish, enter".
3. **Deterministic.** The same context and settings produce the same veto, tested with fixtures.
4. **Typed inputs only.** The rules read enums and numbers, never text.
5. **Recorded.** A veto stores which rule, the values, and the thresholds on the intent
   (`order_intent.veto`).
6. **Fail-open on absence.** Missing, stale, or malformed context vetoes nothing (ADR-004), unless the
   strategy is configured to require context.
7. **Not retroactive.** A veto affects the entry decision only; it never closes or modifies an existing
   position.

## Disabled by Default

A veto rule is **off** for a strategy until counterfactual evidence supports it
(`06-AI-EVALUATION-AND-TEST-DATA.md`). Until then the context is recorded and shown on the approval card but
does not block.

## Approval Card Display

The owner sees the context, the rule that would have vetoed or did veto, and the thresholds, labelled
"context" (`04-UX-UI/02`). In `APPROVAL` mode the owner can still approve an intent that a disabled rule would
have flagged.

## Tests (planned, FR-T09)

A veto blocks an entry and is recorded; the same context does not affect an exit or stop; an unset threshold
never vetoes; unavailable context does not veto; no code path turns context into an entry.
