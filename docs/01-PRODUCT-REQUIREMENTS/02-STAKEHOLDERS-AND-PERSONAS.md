# 02 — Stakeholders and Personas

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Technical Lead |
| **Decided by** | ADR-015 |

## Personas

### Owner / Operator (role `TRADER`)

The only person who trades. Technically capable, comfortable with the analysis platform, and not watching
screens all day.

- **Needs:** to know the Trader is alive; to approve or deny intents quickly with enough context to decide;
  to stop everything in seconds; to see what each strategy has earned and risked; to trust the ledger.
- **Fears:** an order the limits should have blocked; a position with no stop because the bot died; a key
  leak; a silent mismatch with the exchange.
- **Does not want:** a feed of alerts about things that need no action.

### Platform Admin (role `admin`)

Already exists in the analysis platform. In the Trader: **read-only** access to trading data and the audit
log; no ability to trade, approve, or change limits (ADR-015).

### Viewer / Investor (roles `viewer`, `investor`)

Existing analysis-platform roles. Read-only to trading data in the Trader, if the owner enables it. Nothing
in the system assumes such users exist.

### Future Auditor (not designed for)

A second person reviewing the audit log. The audit log is built so this is possible, but no workflow is
designed for it.

## Non-Human Actors

| Actor | Behavior |
|---|---|
| **Strategy Engine** | Produces signals; has no authority over limits or credentials |
| **Watchdog** | Detects a stalled Trader or feed; raises alerts; may trigger `HALT` |
| **Reconciler** | Compares ledger with the exchange; may trigger `HALT` |
| **AI and Kronos context** | May veto an entry; no other authority |

## Stakeholders Without a Role in the System

Indodax (counterparty and rule-setter, including its terms on automated trading and market manipulation,
OQ-1) and any regulator or tax authority (OQ-1). Their requirements are the owner's responsibility to
identify.
