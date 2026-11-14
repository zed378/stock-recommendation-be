# 10 — Indodax Self-Trade Prevention and Fees

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-006 |
| **Open items** | OQ-1 (resolved, ADR-037), OQ-5, OQ-22 (resolved, ADR-035 and ADR-042) |

Sources: `Self-Trade Prevention-TradeAPI.md`, `Public-RestAPI.md`, `Private-websocket.md`.
**Documented, not yet observed.**

## Self-Trade Prevention (STP)

A self-trade is a buy and a sell from the same account (`user_id`) matching in the book. Indodax says this
"distorts price discovery, inflates trading volume, and constitutes market abuse if done intentionally" and
that it "strictly prohibits any form of market manipulation". It also says automated systems can cause
accidental self-trades.

| Point | Detail |
|---|---|
| Effective | STP parameters take effect on **Jul 14, 2026**, so they are in force at the time of writing. Orders before that date are not retroactively evaluated |
| Default | STP applies automatically with fixed default parameters; users can set it per order |
| Trade API 2.0 parameter | `selfTradePreventionMode`: `EXPIRE_TAKER`, `EXPIRE_MAKER` (default), `EXPIRE_BOTH` |
| Legacy parameter | `smp_cancel`: `MAKER` (default), `TAKER`, `BOTH`. Not used |
| Visibility | An order cancelled by STP shows `cancelReason = SELF_TRADE_PREVENTION` in `order/histories` |

### What the Trader Does

- It sends `selfTradePreventionMode` **explicitly** so behavior is not left to a default. **The value is `EXPIRE_TAKER`** (ADR-035): the new order expires and the resting order is kept.
  (`EXPIRE_MAKER`, the exchange default, would cancel the resting order and let the new one proceed.)
- It avoids self-trades by construction: at most one working order per pair and side per strategy, and an
  exit never rests on the opposite side of a working entry for the same pair.
- An order cancelled with `SELF_TRADE_PREVENTION` is a reconciliation signal and a `WARN`. It means the
  design failed to avoid a self-match.
- The owner should read Indodax's terms on automated trading and market manipulation (OQ-1). Nothing in these
  documents is legal advice.

## Fees

| Source | What it gives |
|---|---|
| `GET /api/pairs` (some entries) | `trade_fee_percent`, `trade_fee_percent_taker`, `trade_fee_percent_maker`. The sample shows 0.2 percent taker, 0.1 percent maker for one pair |
| `GET /api/v2/myTrades` | `commission` = **fees plus applicable taxes**, `commissionAsset`, `isMaker` |
| Private WebSocket `fillInformation` | Separate **fee**, **tax**, and **clearing** amounts and rates per fill |

The sample WebSocket fills show a fee rate, a tax rate, and a clearing rate; the rates differ between a
maker and a taker fill. A fill's cost is therefore more than the headline fee percentage.

### Consequences

1. **The cost model cannot use one percentage.** It needs maker and taker fee, tax, and clearing
   (`05-MODULE-SPECIFICATIONS/06`). The values for the owner's account are unknown (OQ-5); they must be
   observed, not assumed from a sample.
2. **Under REST-only polling the split is not available** from `myTrades`. The ledger stores the combined
   `commission` and leaves `fee`, `tax`, `clearing` empty (`05/05`).
3. **Round-trip cost matters.** A strategy that trades often pays maker or taker fee, tax, and clearing on
   both sides. This is one reason for the swing horizon and the LIMIT-first policy (ADR-006, ADR-012).
4. **Tax treatment** is outside this system. The `tax` that appears per fill is a charge shown by the
   exchange; whether the owner has further obligations is OQ-1.

## To Verify Live (OQ-5, OQ-18)

The real fee, tax, and clearing for the owner's account tier, per maker and taker; what `commission`
contains exactly; and whether a TAPIv2 REST call exposes the split.
