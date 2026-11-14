# 09 — Architecture Decisions

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |

Index of the ADRs that shape the architecture. Full text: `../../MEMORY/DECISIONS.md`.

| ADR | Shapes | Document |
|---|---|---|
| 001 | Separate service and package | `00`, `02`, `03` |
| 004 | AI outside the order path | `03`, `../08-AI-AGENT/` |
| 006 | LIMIT-first, MARKET for emergencies | `../05-MODULE-SPECIFICATIONS/04` |
| 007 | Bot-side stops, watchdog | `07`, `../05-MODULE-SPECIFICATIONS/09` |
| 009 | Risk Engine and breakers | `03`, `../05-MODULE-SPECIFICATIONS/03` |
| 010 | Kill switch tiers | `03`, `../05-MODULE-SPECIFICATIONS/08` |
| 011 | Polling only | `05` |
| 021 | Schema and role isolation | `02`, `../03-DATA-MODEL/07` |
| 022 | Reconciliation | `05`, `../05-MODULE-SPECIFICATIONS/10` |
| 024 | Idempotent orders | `07`, `../05-MODULE-SPECIFICATIONS/04` |
| 025 | `Decimal` money | `../03-DATA-MODEL/04` |
| 026 | Write-ahead orders | `07`, `../05-MODULE-SPECIFICATIONS/04` |
| 027 | One active instance | `07` |

## When an ADR Is Required

Before introducing any of:

- a new database, queue, cache, or message broker;
- a new web framework or language runtime;
- a new outbound integration or a new inbound surface;
- a second exchange or a second quote currency;
- a change to the analysis platform's architecture test;
- any code path that could move funds off the exchange.

The last two need the owner's explicit approval, not only an ADR.

## Decisions Still Open That Affect Architecture

OQ-3 (whether a TAPIv2 key can use the Deadman Switch).
