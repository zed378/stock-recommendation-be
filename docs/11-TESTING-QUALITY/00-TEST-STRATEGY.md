# 00 — Test Strategy

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | QA Engineer |
| **Decided by** | ADR-001, ADR-013, ADR-024 |

## Principles

1. **No test calls the production exchange.** The whole order path runs against a mock exchange
   (`07-FIXTURES-AND-MOCK-SERVERS.md`). Indodax offers no sandbox, so the mock carries the burden.
2. **A control is tested by removing it.** For each risk check, the kill switch, and each guard, there is a
   test that **fails when the control is deleted or weakened**. A test that still passes without the control
   proves nothing.
3. **An assertion that something was tested is not evidence. Name the test.**
4. **A passing test on fixtures is not a verified exchange behavior.** A connector verified only against
   fixtures is described as "not yet verified against the live exchange".
5. **A backtest or paper result is not a test of profitability.**
6. **Deterministic.** Time, randomness, and the exchange are injected, so a test is repeatable.

## Layers

| Layer | File | Scope |
|---|---|---|
| Unit | `01` | Pure logic: strategy, sizing, risk checks, state machine, idempotency ids, `Decimal` |
| Connector contract | `02` | Every Indodax method against the mock |
| Integration | `03` | Components together with PostgreSQL and the mock: write-ahead, crash recovery, lease, reconciliation |
| End-to-end acceptance | `04` | The use cases, in all three modes |
| Security | `05` | Secrets, permissions, redaction, privileges, replay |
| Performance and resilience | `06` | Rate limits, failure injection, soak |

## Markers and Selection

Following the analysis platform's pattern: the hermetic suite runs by default; PostgreSQL-dependent tests are
opt-in; a `live_readonly` marker exists for the owner-led read-only check, is **always deselected**, and
refuses to run without an explicit confirmation. There is no marker that places a real order.

## Guard Tests (permanent)

| Guard | Asserts |
|---|---|
| Boundary | `aidss` does not import `aidss_trader`; the reverse is limited to the documented interface |
| Analysis platform | `tests/test_architecture_constraints.py` passes unmodified |
| No withdrawal | The connector's public methods equal the allowlist in `06/01`; no route or identifier names withdrawal, deposit, or fiat |
| No order route | No operator route accepts order-entry parameters |
| Order path | Order-mutating connector methods are called only from the Order Manager and the kill switch, and never without a preceding risk result |
| No float | No float reaches the ledger or the order payload builder; no float column in `trading` |
| No MARKET | No entry or normal-exit path emits `MARKET` |
| Paper isolation | In `PAPER`, zero signed order requests are sent |
| Secrets | No sentinel secret appears in any log, response, notification, or stored raw response |
| Privileges | `trader_rw` cannot `UPDATE` or `DELETE` append-only tables |
| Veto | No code path turns AI context into an entry |

## Definition of a Complete Task's Tests

The task's record names each test, the markers needed to run it, and what it does **not** cover.

## Coverage

Coverage is reported but is not a target by itself. The measure that matters is the guard list above and the
named test per requirement (`01-PRODUCT-REQUIREMENTS/07`).

## Evidence Required Before Live Money

The release checklist (`12-DELIVERY-PLAN/05`) requires named passing tests for every guard, a kill-switch
drill on the mock, a restore rehearsal, and the owner-led read-only live verification.
