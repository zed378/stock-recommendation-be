# 01 — Product Scope

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-002, ADR-005, ADR-011, ADR-012, ADR-013 |

## In Scope (MVP)

| Area | Included |
|---|---|
| Exchange | Indodax, Trade API 2.0, spot only |
| Pairs | Owner allowlist of **IDR-quoted** pairs |
| Horizon | 4H and 1D candles |
| Orders | `LIMIT` (GTC, optionally MOC); `MARKET` for emergency exits only |
| Strategies | Pluggable interface; one reference strategy, EMA plus ADX trend-following |
| Modes | `PAPER`, `APPROVAL`, `AUTO` per strategy |
| Risk | Circuit breakers, risk-based sizing, per-pair and total exposure |
| Controls | Tiered kill switch; bot-side stops with watchdog |
| Data | REST polling of candles, prices, orders, trades, balances |
| Accounting | Append-only ledger, WAC PnL, fee and tax and clearing recorded separately |
| Verification | Backtest with a cost model; paper trading; reconciliation |
| Context | Read-only AI and Kronos context from the analysis platform, as veto |
| Operations | Credential admin screen, operator dashboard, approval queue, audit log, mobile notifications |

## Out of Scope (permanent unless a new ADR says otherwise)

- **Withdrawals, deposits, and fiat movements of any kind** (ADR-013).
- Execution on the analysis platform's equity (IDX) assets (ADR-001).
- Using model text to create or alter an order (ADR-004).

## Out of Scope for the MVP (deferred)

| Item | Why deferred |
|---|---|
| USDT pairs | Second quote currency complicates accounting and risk (ADR-005) |
| WebSocket market data and private order-update stream | Not needed at swing horizon; private token is legacy-auth (ADR-011, ADR-002) |
| Deadman Switch | Legacy-auth only (ADR-007, OQ-3) |
| Intraday and scalping horizons | Cost and latency (ADR-012) |
| Pair auto-discovery | Allowlist only (ADR-005) |
| AI-triggered strategies | ADR-004 |
| Multiple users, two-person approval | ADR-015 |
| Futures, margin, lending | Not offered through this API surface in the docs read |
| Tax reporting | OQ-1 |

## MVP Boundary

The MVP is complete when one strategy can run through `PAPER`, then `APPROVAL` with a small amount of real
capital, with every control in `12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` verified. `AUTO` is **not** part
of the MVP's definition of done: it requires the owner to set and meet the promotion thresholds (OQ-12).

## Explicit Non-Goals

- Maximising return. The system's goal is bounded, inspectable risk.
- Supporting every Indodax endpoint. Only those in `06-INTEGRATIONS/06` and `07` are implemented.
- Universal UI polish. The operator surface exists to approve, observe, and stop.
