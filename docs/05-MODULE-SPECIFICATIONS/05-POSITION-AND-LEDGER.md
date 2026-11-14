# 05 — Position and Ledger

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Trading Engineer |
| **Decided by** | ADR-022, ADR-025 |
| **Open items** | OQ-5 |

Schema: `03-DATA-MODEL/04-ORDER-POSITION-LEDGER-SCHEMA.md`.

## Ledger

Append-only. Each fill produces entries: base asset in or out, quote asset (IDR) out or in, and the
costs as separate entries (`FEE`, `TAX`, `CLEARING`). The Trader's database role cannot `UPDATE` or
`DELETE` these rows (FR-T26).

### Where the Cost Split Comes From (OQ-5)

`GET /api/v2/myTrades` returns one `commission` that **includes trading fees and taxes** in a single
number. The Private WebSocket `fillInformation` splits them into fee, tax, and clearing with rates, but the
WebSocket is deferred (ADR-011). So under REST-only polling the split is not available. The ledger therefore
records the combined `commission` as one `FEE` entry (kind `COMMISSION_COMBINED`) and fills `fee`, `tax`, and
`clearing` columns **only when a source provides them**. It never estimates a split. Whether the split is
needed for the owner's reporting, and how to obtain it without the WebSocket, is OQ-5.

## Position

Derived from the ledger per (`pair`, `origin`): signed quantity and weighted average cost. No stored copy is
the source of truth. Long-only; quantity never goes negative, and a sell exceeding the position is an
integrity error that halts.

## Weighted Average Cost (ADR-022)

- A buy updates average cost: `(old_qty x old_cost + fill_qty x fill_price + costs) / (old_qty + fill_qty)`.
- A sell realizes `(fill_price - average_cost) x qty` less its costs, and leaves average cost unchanged.
- Costs on a buy raise the cost basis; costs on a sell reduce proceeds. Both are visible as separate lines.

## PnL

| Figure | Definition |
|---|---|
| Realized | Sum over closed quantity, after all costs |
| Unrealized | `(last_price - average_cost) x quantity`, with the price's timestamp stated |
| Total | Realized plus unrealized, **within one origin only** |

Paper, live, and backtest are never summed (FR-T28).

## Corrections

If the ledger is wrong, the original rows stay. An `ADJUSTMENT` entry with a mandatory reason and an audit
row corrects the effect. The Trader never rewrites history, and never "fixes" a reconciliation difference
without a recorded cause (`10-RECONCILIATION.md`).

## Equity

Equity for risk purposes is **not** derived from the ledger: it is read from the exchange balances. The
ledger explains it; it does not replace it.

## Dust

A remainder below the pair's minimum cannot be sold. It stays in the position, is shown separately as
dust, and is excluded from exposure only if the owner configures that.
