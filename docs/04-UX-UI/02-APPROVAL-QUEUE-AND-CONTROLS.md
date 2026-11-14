# 02 — Approval Queue and Controls

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer (frontend), Risk Engineer |
| **Decided by** | ADR-003, ADR-010, ADR-020 |
| **Open items** | OQ-12, OQ-22 (resolved, ADR-035 and ADR-042) |

## Approval Card (FR-T22)

Shown for an intent in `AWAITING_APPROVAL`.

| Section | Content |
|---|---|
| Header | Pair, side, mode `APPROVAL`, strategy and version, time to expiry |
| Order | Type `LIMIT`, price, quantity, estimated IDR value |
| Protection | Stop price, target price, the IDR amount at risk and its share of equity |
| Why | The rule outputs that produced it, in plain statements |
| Context | The AI and Kronos context that was attached, with its age, and any veto. Labelled as context |
| Limits | Each limit's headroom after this order, and any that came within a configured margin |
| Costs | Expected fee for maker and for taker, as a stated assumption (OQ-5) |

**Actions:** Approve, Deny (with an optional reason). The card states that **approval applies to exactly
this price and quantity**. If the market moves and the intent is re-priced, it returns to this queue as a
new approval.

An intent expires at `expires_at`; the card shows the real expiry, not a pressure countdown.

## Kill Switch Controls

Always present (`00-UX-PRINCIPLES.md`).

| Control | Effect | Confirmation |
|---|---|---|
| **HALT** | No new orders | One confirmed click |
| **CANCEL** | `HALT` and cancel all open orders | Confirmation listing the count of open orders |
| **FLATTEN** | `CANCEL` and close all positions at market | Lists each position and approximate value; owner must type `FLATTEN` |
| **Resume** | Leave `HALTED` | Requires a note; shows the halt reason and any unresolved reconciliation difference. Disabled while a difference or an `UNKNOWN` order is unresolved |

While a kill action runs, the controls show each step as it completes or fails (`kill_switch_step`).

## Strategy Promotion Screen (FR-T23)

Shows for the chosen strategy the current mode, the next mode, and **each gate** with its measured value,
its threshold, and pass or fail. The thresholds come from configuration (OQ-12) and are not displayed as
defaults when unset: an unset threshold blocks promotion and says so. Promotion records the evidence
(`mode_change.evidence`). Demotion is one confirmed action and needs no evidence.

## Limits and Allowlist Editor

Edits create a new version, never overwrite. Each field shows its current value or "unset". Saving a
limit that **raises** exposure shows the effect and requires confirmation. All changes are audited.

## Strategy Parameters Editor

Saving creates a new `strategy_version` and returns the strategy to `PAPER`. The screen states this before
saving.

## Credential Screen

See `../05-MODULE-SPECIFICATIONS/13-CREDENTIAL-ADMINISTRATION.md`. The key and secret are write-only fields;
the screen never displays them back, only a masked hint and the time of the last successful read-only test.
