# 04 — Integration Topology

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Integration Engineer |
| **Decided by** | ADR-002, ADR-011 |
| **Open items** | OQ-3, OQ-4, OQ-6 (resolved, ADR-041 and ADR-043), OQ-13 (decided, ADR-032) |

Endpoint paths are from the official Indodax documentation and have **not been observed live**
(`00-PROJECT-CONTEXT/04-ASSUMPTIONS-CONSTRAINTS.md`).

## Flows to Indodax

| Flow | Direction | Endpoint | Auth | Used by |
|---|---|---|---|---|
| Candles | Pull | `GET /tradingview/history_v2` (public host `indodax.com`) | none | Market Data |
| Pair metadata | Pull | `GET /api/pairs`, `GET /api/price_increments` (public) | none | Market Data |
| Server time | Pull | `GET /api/server_time` (public) | none | Connector (skew check) |
| Last price | Pull | `GET /api/v2/ticker/price` (multi-symbol) | none | Exit Monitor |
| Best bid/ask | Pull | `GET /api/v2/ticker/bookTicker` (multi-symbol) | none | Intent Builder, Risk (deviation guard) |
| Account | Pull | `GET /api/v2/account` | signed | Risk, Reconciler, start check |
| Create order | Push | `POST /api/v2/order` | signed | Order Manager |
| Cancel order | Push | `DELETE /api/v2/order` | signed | Order Manager, Kill Switch |
| Open orders | Pull | `GET /api/v2/openOrders` | signed | Order Manager, Reconciler |
| Order detail | Pull | `GET /api/v2/order` | signed | Order Manager |
| Order history | Pull | `GET /api/v2/order/histories` | signed | Reconciler |
| Trade history | Pull | `GET /api/v2/myTrades` | signed | Ledger, Reconciler |

Public Trade API 2.0 base is `https://api.indodax.com`. The signed endpoints' base is the same host in the
Private API document; the STP document names `https://tapi.indodax.com` as the Trade API 2.0 base. Which is
canonical is unresolved (`06-INTEGRATIONS/11-INDODAX-DOCS-DISCREPANCIES.md`). The base URL is
configuration, not a constant.

## Not Used

| Endpoint | Reason |
|---|---|
| Legacy `https://indodax.com/tapi` (any `method`) | ADR-002 |
| `POST /countdownCancelAll` (Deadman Switch) | Legacy auth only (ADR-007, OQ-3) |
| Private WebSocket token and channel | Legacy auth only (ADR-011) |
| Market-data WebSocket | Deferred (ADR-011) |
| All `capital/*` and `fiat/*` endpoints | Withdrawal and deposit; never implemented (ADR-013) |

## Flows to Other Systems

| Flow | Direction | Notes |
|---|---|---|
| Analysis context | Pull from Trader | Read-only; failure does not block (ADR-004). Post-MVP; option B (ADR-032) |
| Notifications | Push | Telegram (ADR-031) plus in-app |
| Operator surface | Inbound | Only the owner |

## Sequencing Constraints

- Public data and signed calls come from the **same IP**, so their rate limits are shared per IP
  (`06-INTEGRATIONS/08`). The budget in `08-CACHING-AND-PERFORMANCE.md` accounts for that.
- Multi-symbol ticker calls cost one request regardless of pair count, which is why the Exit Monitor uses them.
