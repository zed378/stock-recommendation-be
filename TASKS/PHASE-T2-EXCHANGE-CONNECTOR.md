# Phase T2 — Exchange Connector

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T1 complete |
| **Exit criteria** | A connector implementing exactly the allowlist in `docs/06-INTEGRATIONS/01`, with a mock exchange, contract tests for every method and case, and the owner-led read-only verification done and recorded, with `06-INTEGRATIONS/11` updated |

**Needs from the owner:** OQ-3, OQ-4, OQ-18 (a Read-only key for T2-07).

**Everything here is documented, not yet observed, until T2-07.**

---

### T2-01 — Mock exchange server

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-01 |
| **Spec refs** | `docs/11-TESTING-QUALITY/07-FIXTURES-AND-MOCK-SERVERS.md` · `docs/06-INTEGRATIONS/04` to `08` |
| **Spec required** | yes |

**Definition of Done**
- [ ] The endpoints and behaviors in `11/07`, scriptable, seeded
- [ ] Verifies HMAC-SHA256 with **test-only keys defined in tests**
- [ ] Enforces `recvWindow`, rate limits, duplicate `newClientOrderId` (`-2010`), 7-day history windows,
      visibility lag, both documented forms of quirky fields
- [ ] States what it does **not** model

**Abuse cases**
- Making the mock more forgiving than Indodax so tests pass.
- Copying Indodax's sample keys into it.

### T2-02 — Connector core

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-01, T1-04 |
| **Spec refs** | `docs/06-INTEGRATIONS/01-CONNECTOR-CONTRACT.md` · `04-INDODAX-AUTH-AND-SIGNING.md` · `08-INDODAX-ERRORS-AND-RATE-LIMITS.md` |
| **Spec required** | yes |

**Definition of Done**
- [ ] Signing per `06/04`; one place for parameters; signs the transmitted string
- [ ] Normalized error classes; retry classes (safe, verify-then-act, never blind)
- [ ] Method allowlist enforced by a test; **no withdrawal, deposit, or fiat method**
- [ ] `Decimal` parsing at the edge; both documented forms accepted
- [ ] No key, secret, or signature in any log

**Abuse cases**
- A "generic request" method that lets any path be called.

### T2-03 — Public market data

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-02 |
| **Spec refs** | `docs/06-INTEGRATIONS/05-INDODAX-MARKET-DATA.md` · `docs/03-DATA-MODEL/03` |
| **Spec required** | no |
| **Open numbers** | OQ-4 |

**Definition of Done**
- [ ] Pairs, increments, server time, OHLC (`240`, `1D`), tickers, bookTicker, depth
- [ ] Idempotent candle ingest; unfinished candle excluded; gaps recorded
- [ ] Pair disagreement or a missing field blocks the pair
- [ ] Contract tests for every case in `11/02`
- Test names: `test_candles_ingest_is_idempotent`, `test_stale_price_is_marked_stale`,
  `test_order_below_minimum_is_not_created`

### T2-04 — Account read and permission check

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-02 |
| **Spec refs** | `docs/06-INTEGRATIONS/07` · ADR-013 |
| **Spec required** | no |

**Definition of Done**
- [ ] `GET /api/v2/account`; refuses trading if `canWithdraw` or `canWithdrawFiat` is true or `canTrade` is
      false
- [ ] Test `test_withdraw_permission_blocks_start`

### T2-05 — Throttle and clock handling

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-02 |
| **Spec refs** | `docs/06-INTEGRATIONS/08` · FR-T17, FR-T18 |
| **Spec required** | no |
| **Open numbers** | none (skew limit 250 ms, ADR-041) |

**Definition of Done**
- [ ] Token buckets per scope below the strictest limits
- [ ] Skew check against `server_time`; halt before signing beyond tolerance
- [ ] Tests `test_client_never_exceeds_rate`, `test_clock_skew_halts_before_signing`

### T2-06 — Order endpoints against the mock

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-02, T2-01 |
| **Spec refs** | `docs/06-INTEGRATIONS/06-INDODAX-ORDERS.md` · `07` |
| **Spec required** | yes |
| **Open numbers** | none (STP value decided, ADR-035) |

**Definition of Done**
- [ ] `create_order`, `cancel_order`, `get_order`, `get_open_orders`, `get_order_history`, `get_my_trades`
- [ ] `clientOrderId` always set; `STOP_LIMIT`, `FOK`, and `BUY MARKET` never sent
- [ ] These methods are importable only by the Order Manager and the kill switch (a guard)
- [ ] All contract cases, including timeout on create with a write-ahead-compatible result

**Abuse cases**
- Testing only the happy path of create. The timeout case is the one that matters.

### T2-07 — Owner-led read-only live verification

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T2-06 |
| **Spec refs** | `docs/06-INTEGRATIONS/03` to `11` · `docs/06-INTEGRATIONS/14-INDODAX-LIVE-VERIFICATION-PLAN.md` · `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` |
| **Spec required** | yes |
| **Owner-led** | **yes** |

**An agent prepares this and stops.** It needs the owner's Read-only key and explicit instruction.

**Definition of Done**
- [ ] The owner provides a **Read-only** key by a means outside the repository and chat history
- [ ] The `live_readonly` run is explicit, confirmed, and logs no secret
- [ ] Each item in `06/11` that can be observed read-only is observed and recorded with the date
- [ ] Redacted recorded fixtures added; the mock corrected where it differed
- [ ] `06/03` to `06/11` amended through the deviation protocol; "not yet observed" removed only where
      observed
- [ ] OQ-3 and OQ-4 answered where possible

**Abuse cases**
- Using a key with Trade permission "just to test an order". Not part of this task.
- Reporting "verified" for an endpoint that was not called.
