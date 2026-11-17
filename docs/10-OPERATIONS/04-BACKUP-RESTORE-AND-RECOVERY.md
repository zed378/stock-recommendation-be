# 04 — Backup, Restore, and Recovery

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-014, ADR-021, ADR-022 |
| **Open items** | OQ-17 (custody decided, ADR-029), OQ-20 (decided, ADR-040) |

## What Is Backed Up

The `trading` schema: ledger, orders, fills, audit, strategies, limits, credential ciphertext. It is the
Trader's memory and a financial record.

## What Is Not Backed Up With It

The **master key** (the file secret named by `AIDSS_TRADER_MASTER_KEY_FILE`). A dump plus the key recovers the Indodax credential; the two
are never stored together (ADR-014). Losing the key makes the ciphertext unreadable, which is recoverable:
the owner re-enters a key (`05/13`).

## Mechanism and Schedule

A schema-scoped dump (`pg_dump -n trading`), taken with a role that can read it. The owner takes it **manually** (ADR-040); **frequency and retention** are their choice (worksheet L1). Take one before every release (`03`).

## Where (ADR-040)

The owner copies backups **manually** to an external disk or their own PC. Nothing automatic copies the dump off
the host, so the **RPO of the audit trail is the time since the owner last copied it**, and a host loss loses
everything since then. The exchange remains the source of truth for trading state (ADR-022), so state can be
rebuilt; the audit trail, strategy history, and local annotations cannot.

What stays mandatory: a backup **before every release** (`03`) and a restore rehearsal in the release checklist. A
reminder or an automatic off-host copy would be possible later additions and would need the owner's approval.

**Current VM status (2026-11-15):** The pre-deployment dump (`~/aidss-pre-trader-*.sql.gz`) resides on the same
host disk (`10.1.200.13`) as the running PostgreSQL container. Per ADR-040 this is accepted while no live funds are
at risk, but a disk or host failure would lose both the database and that local dump until the owner copies dumps
off-host to their PC or an external drive. The owner can pull an encrypted off-host cluster copy directly to their workstation using `deploy/trader/backup_offhost.sh` from Git Bash (see runbook R9).

## Restore

| Step | Action |
|---|---|
| 1 | `HALT` or ensure the Trader is stopped |
| 2 | Restore the `trading` schema into a scratch database first and inspect |
| 3 | Restore into place with the correct roles and privileges (`03-DATA-MODEL/07`) |
| 4 | Verify the privilege boundary: `trader_rw` cannot `UPDATE` or `DELETE` append-only tables |
| 5 | Start the Trader; it **reconciles with the exchange**, which is the source of truth (ADR-022) |
| 6 | Any difference halts; the owner resolves it |
| 7 | The owner resumes explicitly |

A restore older than the last fills creates `FILL_MISSING_LOCALLY` differences; the exchange history
endpoints cover up to **7 days** per request, so a restore from more than a week ago cannot be fully repaired
from those endpoints alone (`02-ARCHITECTURE/05`).

## Recovery Without a Database

If the database is lost entirely and no backup exists, the exchange still holds orders, trades, and
balances. The Trader can be re-initialized and a reconstructed ledger built from `myTrades` within the
available history, marked as **reconstructed**. This loses the audit trail and the strategy history and is a
last resort.

## Rehearsal

A restore is rehearsed before the first live release and then at a schedule the owner sets. An untested
backup is not a backup. The rehearsal is recorded in `MEMORY/records/` with the time it took.

## RPO and RTO

The owner's targets (worksheet L1). With manual backups (ADR-040) the audit-trail RPO is the interval between the owner's copies. The design makes the exchange the source of truth, so the RPO of trading
*state* is bounded by reconciliation; the RPO of the **audit trail** is the backup interval.

## Moving to another host

A move is a restore with extra care about the two secrets that must travel byte for byte and never inside a backup (the JWT secret and the Trader master key).
`09-MIGRATION-RUNBOOK.md` and the kit in `deploy/production/` (`restore.sh`, `fingerprint.sh`, `preflight.sh`) cover it; `restore.sh` is also the way to restore a `pg_dumpall` into a fresh PostgreSQL container for a recovery.
