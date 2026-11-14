# 00 — Environments and Configuration

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-014, ADR-021 |
| **Open items** | OQ-9, OQ-14 (resolved, ADR-028), OQ-17 (custody decided, ADR-029) |

## Environments

| Environment | Exchange | Purpose |
|---|---|---|
| **Local** | Mock exchange | Development and the hermetic test suite |
| **CI** | Mock exchange | Gates on every change |
| **Production** | Real Indodax | The only environment with a real exchange |

**There is no exchange sandbox.** The Indodax documentation read lists production base URLs only, with no
testnet or paper endpoint. Everything short of real money is therefore verified against the mock exchange
(`11-TESTING-QUALITY/07`), and the first contact with the real exchange is a **read-only** check on the
owner's instruction (T2-07), followed by `APPROVAL` mode with a small amount (T5-06). `PAPER` mode is the
Trader's own simulation, not an exchange feature.

## Two Kinds of Configuration

| Kind | Where | Examples |
|---|---|---|
| **Infrastructure** | Container environment | Database URL and password for `trader_rw`, `AIDSS_TRADER_MASTER_KEY_FILE` (the **path** to the master-key file secret, never the key, ADR-029), the exchange base URL and public host (configuration, not constants, `06/11` D1), log level, instance name |
| **Operational** | The `trading` schema, edited through the operator surface | Risk limits, allowlist, strategy parameters, polling intervals, notification threshold, credential ciphertext |

The Indodax credential and every number that limits loss are **not** environment variables. They are stored
in the database through the audited operator surface, following the platform's existing "configuration in
the database, secrets encrypted" pattern.

## Settings With No Default

Each of these has **no default value anywhere**. Until the owner sets it, the affected strategy is disabled
(FR-T11):

| Setting | Open question |
|---|---|
| Daily loss, drawdown, consecutive-loss limits | OQ-9 |
| Per-trade risk percent, per-pair and total exposure, max order value, open positions | OQ-9 |
| Freshness limit; price-deviation percent; cooldown; trading window | OQ-9 |
| Strategy parameters | OQ-11 |
| Promotion thresholds | OQ-12 |
| Veto thresholds | Set at the post-MVP evidence review (ADR-045) |
| Liquidity filter thresholds | OQ-8 (the allowlist is decided, ADR-044) |

## Naming (proposed)

Environment variables use the prefix `AIDSS_TRADER_`. Infrastructure only; the list is fixed when T1-01
scaffolds the service.

## Visibility to Other Roles

Whether `investor` and `viewer` can see trading data at all is a setting the owner can switch off
(`01-PRODUCT-REQUIREMENTS/06`).

## Secrets Handling

`09-SECURITY-PRIVACY/02`. The master key is read from a file secret mounted into the container (ADR-029) and is never committed or baked into an image.
No example value is given in any document.
