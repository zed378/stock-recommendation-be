# 00 — AI Boundaries in Trading

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer, reviewed by Technical Lead |
| **Decided by** | ADR-004 |
| **Open items** | OQ-13 (decided, ADR-032) |

## The Rule

**Deterministic rules decide. AI and Kronos-base are context, and may veto an entry.**

## What AI May Do

| Allowed | Condition |
|---|---|
| Provide context attached to an intent | Structured fields only; stored with a timestamp |
| **Veto an entry** | Through a deterministic rule on structured fields (`02-VETO-RULES.md`) |
| Explain to the owner | Shown on the approval card, labelled as context |

## What AI Must Never Do

| Forbidden | Why |
|---|---|
| Create an intent or an order | Only strategies create signals (ADR-004) |
| Choose, change, or approve a price, quantity, stop, or target | Computed deterministically from rules and limits |
| Change a limit, a mode, an allowlist, or a credential | Owner-only, audited |
| Delay, cancel, or alter a stop or a kill-switch action | Protective paths are independent of AI |
| Trigger anything automatically from free text | No model text reaches an order path |
| Receive account data | Positions, balances, equity, and key material are never sent to a model |
| Perform "automatic remediation" of any kind | Out of scope; needs a new ADR and explicit approval |

## Why a Veto Only Blocks

A veto is an additional reason **not** to trade. It can make the system trade less, never more. This is the
safe direction: a model error or a manipulated input can at worst cost an opportunity, not create an order.

## Missing or Failed AI Is Normal

If context is unavailable, late, or malformed, **rules proceed** unless a strategy is explicitly configured to
require it (ADR-004). The absence is recorded on the intent. This also means the first release can ship with
no AI context at all (`06-INTEGRATIONS/13`, option D).

## Execution Language

The analysis platform rejects model output that reads as an instruction to trade
(`aidss.prompts.language.find_execution_language`). The Trader does not depend on that filter, because
nothing a model writes ever reaches an order. The Trader consumes only typed fields: a label from a closed
set, a number, and a flag.

## Data Minimization

Analysis requests to the platform carry the pair, timeframe, and (under option B) public candles. They carry
**no account information**. The Trader's own position or balance never leaves it for any model.

## Untrusted Input

The analysis platform ingests news and social text. Such text can carry prompt injection. Because the only
effect of model output on the Trader is a typed veto, an injected instruction cannot place, size, or alter an
order. It could at most cause a spurious veto (a missed trade). That is the bounded worst case
(`09-SECURITY-PRIVACY/00-THREAT-MODEL.md`).

## Evaluation Before Use

A veto is enabled for a strategy only after counterfactual evidence that it helps
(`06-AI-EVALUATION-AND-TEST-DATA.md`). Until then context is recorded but does not veto.
