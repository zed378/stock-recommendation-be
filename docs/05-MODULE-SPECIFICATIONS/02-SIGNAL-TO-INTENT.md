# 02 — Signal to Intent

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-006, ADR-008, ADR-025 |
| **Open items** | OQ-9, OQ-22 (resolved, ADR-035 and ADR-042) |

The Intent Builder turns an `ENTRY` or `EXIT` signal into a sized, quantized **order intent**. It does not
send anything.

## Entry Sizing (ADR-008)

```
risk_amount   = equity x risk_per_trade_pct
raw_qty       = risk_amount / (entry_price - stop_price)
qty           = floor_to_increment(raw_qty, pair.quantity_increment)
qty           = min(qty, per_pair_exposure_cap_qty, total_exposure_cap_qty, max_order_idr / entry_price)
```

- `equity` is read **fresh** from the exchange balances at decision time (`01-SOURCE-OF-TRUTH-MATRIX.md`).
- Rounding is always **down**, so the realized risk never exceeds `risk_amount`.
- An entry with no stop, or with `entry_price <= stop_price`, is **rejected** before the Risk Engine.
- If `qty` is below the pair minimum (`trade_min_traded_currency`) or its value is below
  `trade_min_base_currency`, no order is created and the intent is recorded as `RISK_REJECTED` with reason
  `below_minimum`.
- All arithmetic is `Decimal` (ADR-025).

`risk_per_trade_pct`, `max_order_idr`, and the exposure caps are owner settings (OQ-9); unset means the
intent is not built (FR-T11).

## Price

Entries and normal exits are `LIMIT` orders (ADR-006). **The price rule (ADR-035):** a buy is placed at the
**best bid** and a sell at the **best ask** (maker-first), quantized to the pair's price increment. Entries use
`MOC` (maker or cancel) so an order that would cross is cancelled rather than filled as a taker. **The wait before repricing is 5 minutes and the maximum is 3 reprices** (ADR-042). Price is quantized to the pair's price increment. The price-deviation guard (`03-RISK-ENGINE.md`)
compares the chosen price with the current best bid and ask.

## Exit Intents

- **Signal exit** (trend broke): a `LIMIT` sell for the position quantity.
- **Stop exit**: created by the Exit Monitor, `MARKET`, through the Risk Engine's emergency profile
  (`09-EXIT-MONITOR.md`).
- Quantity is the current position, rounded down to the increment. Any remainder below the pair minimum is
  dust and cannot be sold; it is recorded and reported, not hidden.

## What an Intent Contains (FR-T08)

Strategy and version, signal, pair, side, price, quantity, stop, target, risk amount, a snapshot of the rule
inputs and outputs, the analysis context and any veto, mode, and an expiry for `APPROVAL`. The intent alone
must be enough to explain why it exists.

## Idempotency

An intent has a deterministic identity from (`strategy_version`, `pair`, `signal candle open time`, `side`),
so re-evaluating the same candle after a restart cannot create a second intent. The `clientOrderId` is
derived from that identity (ADR-024).

## Veto

An analysis veto (`08-AI-AGENT/02`) is applied here, to **entries only**. A vetoed intent is recorded with
the reason and goes no further. A veto never applies to a stop or a kill-switch exit.
