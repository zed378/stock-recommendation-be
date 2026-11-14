# 00 — Roadmap

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-003, ADR-020 |

Phases follow the reference repository's rule: **never build a Phase N+1 feature while Phase N is
incomplete.** Task cards are in `../../TASKS/`. No dates are given because none were agreed.

## Phases

| Phase | Name | Exit criteria |
|---|---|---|
| **T0** | Specification | `docs/`, `MEMORY/`, `TASKS/`, `CLAUDE.md`, `AGENTS.md` written; open questions listed; the owner has reviewed. **This work.** |
| **T1** | Foundation | `aidss_trader` package, image, Compose service, schema, roles, migrations, guard tests, credential store, audit log. **No exchange calls.** The analysis platform's architecture test still passes unmodified |
| **T2** | Exchange connector (read-only first) | Mock exchange; signing; public market data; account and permission check; throttle and clock; order endpoints against the mock; contract tests; **owner-led read-only verification against the live exchange** and the discrepancy table updated |
| **T3** | Strategy, backtest, paper | Strategy interface and the reference strategy; sizing; backtest with the cost model; paper executor; ledger and PnL; (the analysis bridge is post-MVP, ADR-032) |
| **T4** | Execution core | Risk Engine and breakers; Order Manager with write-ahead and idempotency; lifecycle; Exit Monitor and watchdog; kill switch; reconciliation. All on the mock |
| **T5** | Operator surface and `APPROVAL` | Approval workflow; notifications; promotion; dashboard; export; **`APPROVAL` live with small real capital** (owner-led) |
| **T6** | Hardening and the `AUTO` decision | Security tests and review; resilience tests; runbooks drilled; restore rehearsed; release checklist; the owner decides whether `AUTO` gates are met |

## Dependencies Between Phases

- T2 needs T1's credential store and schema only for storage; the connector itself is independent.
- T3's paper path reuses T4's order state machine, so T4's state machine is built in T3 or earlier as a
  shared piece (T3-04); see the task cards.
- T4 depends on T2 (connector) and T3 (strategy, ledger).
- T5 depends on T4.
- **Live money is introduced only in T5**, after T4 has run on the mock and the owner has set the numbers
  (OQ-9, OQ-12, OQ-16).

## What the Owner Must Decide Before Each Phase

| Before | Open questions |
|---|---|
| T1 | None open: OQ-14, OQ-17, and OQ-24 are decided (ADR-028, ADR-029, ADR-030) |
| T2 | OQ-3, OQ-4, OQ-18 (live read-only verification, which needs a Read key) |
| T3 | OQ-5 (costs), OQ-11 (strategy parameters) |
| T4 | OQ-9 |
| T5 | OQ-12 (thresholds), OQ-16 (capital) |
| T6 | None open (ADR-037, ADR-039, ADR-040) |

## Post-MVP (decided)

AI and Kronos context for crypto: the candle-in endpoint in the analysis platform (T3-06) and the Trader's bridge
in record-only mode (T3-05), then the evidence review before any veto is enabled (ADR-032).

## Not on the Roadmap

WebSockets, the Deadman Switch, USDT pairs, intraday strategies, AI-triggered strategies, multi-user
operation. Each is deferred by an ADR and returns only through a new one.
