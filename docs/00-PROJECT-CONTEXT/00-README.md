# 00 — README: AIDSS Trader Documentation Entry Point

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-001, ADR-017, ADR-023 |

This is the entry point into `docs/`. It documents the **AIDSS Trader**: an autonomous spot-trading
service for IDR pairs on Indodax, designed to sit beside the existing AIDSS analysis platform.

## Read This First

**The Trader is documented but not built.** No `aidss_trader` package, trading table, or Indodax client
exists. These documents are the specification the build will follow. `../TASKS/PROGRESS.md` is the only
authority on what exists.

**The analysis platform is built and is not changing.** It is a decision-support system with no order or
broker path, and that guarantee is kept (ADR-001). Its specification is archived at
`archive/Dokumen_Perencanaan_AI_Investment_Decision_Support.md`; code comments that cite "Section N" refer to
that file.

## What the Trader Is, in Five Lines

1. Trades **IDR spot pairs on Indodax** from an owner-maintained allowlist, using **Trade API 2.0** only.
2. **Deterministic strategies** decide; AI and Kronos-base (CPU) provide context and can veto.
3. Each strategy runs in one of three modes: `PAPER`, `APPROVAL`, `AUTO`, promoted by measurable gates.
4. A **Risk Engine** and a tiered **kill switch** sit between every strategy and the exchange.
5. Indodax is the **source of truth**; the Trader reconciles and halts on any difference.

## Reading Order by Role

| Role | Read |
|---|---|
| Anyone, first | This file, `01-SYSTEM-CONTEXT.md`, `02-GLOSSARY.md`, `03-DECISION-LOG.md` |
| Product and scope | `../01-PRODUCT-REQUIREMENTS/` |
| Architecture | `../02-ARCHITECTURE/`, `../03-DATA-MODEL/` |
| Building or changing the exchange connector | `../06-INTEGRATIONS/03` through `11`, then `01-CONNECTOR-CONTRACT.md` |
| Risk, limits, kill switch | `../05-MODULE-SPECIFICATIONS/03`, `08`, `09`, `../09-SECURITY-PRIVACY/00-THREAT-MODEL.md` |
| AI and Kronos | `../08-AI-AGENT/` |
| Security review | `../09-SECURITY-PRIVACY/` |
| Operating and deploying | `../10-OPERATIONS/` |
| Testing | `../11-TESTING-QUALITY/` |
| Picking up a task | `../../TASKS/README.md`, then `../../TASKS/PROGRESS.md` |

## Document Ownership

| Area | Owner (role, per `../../AGENTS.md`) |
|---|---|
| `00-PROJECT-CONTEXT/`, `12-DELIVERY-PLAN/` | Technical Lead |
| `01-PRODUCT-REQUIREMENTS/` | Technical Lead, with the Owner |
| `02-ARCHITECTURE/`, `03-DATA-MODEL/`, `07-API-CONTRACTS/` | Trading Engineer |
| `04-UX-UI/` | Trading Engineer (frontend) |
| `05-MODULE-SPECIFICATIONS/` | Trading Engineer; Risk Engineer for `03`, `08`, `09` |
| `06-INTEGRATIONS/` | Integration Engineer |
| `08-AI-AGENT/` | Trading Engineer, reviewed by Technical Lead |
| `09-SECURITY-PRIVACY/` | Security Engineer |
| `10-OPERATIONS/` | DevOps Engineer |
| `11-TESTING-QUALITY/` | QA Engineer |

## How to Read the Status Markers

Each document's header carries `Decided by` (ADRs) and `Open items` (backlog entries). A section that
depends on an undecided number says so and names the open question; it does not supply a default.

## Local Development Entry Point

Not available for the Trader. For the analysis platform see `../../README.md` and `../../CLAUDE.md`. The
Trader's own `10-OPERATIONS/01-LOCAL-DEVELOPMENT.md` describes the intended setup.
