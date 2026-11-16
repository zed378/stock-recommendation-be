# Host hardening step 1: `pg_dumpall` backup of the production PostgreSQL (2026-11-16)

First step of the host hardening plan (runbook R15, `deploy/trader/isolate_analysis_role.sql`), which requires "a fresh backup" before any role or password change. Nothing else of the plan was applied.

## What was done

- Cluster dump of `stocks-postgres-1` (PostgreSQL 16) as superuser `aidss`: `pg_dumpall --quote-all-identifiers | gzip -6`, on the VM as `infra`, `umask 077`, into a new directory
  `~/aidss-backups/` (mode `0700`; the older `~/backups/` is owned by root and could not be used). File `pg_dumpall-20261116T100117Z.sql.gz`, 71,658,336 bytes, mode `0600`,
  sha256 `2c71e9d93cfda9857b2fcc717f0ec2e391175640a8c05eb0326025dad9584748`. Source database size 339 MB.
- The master key `~/.aidss-trader-master.key` was **not** copied into the backup directory (ADR-014, ADR-029, runbook R10).

## Verification

- `gzip -t` passed; the dump ends with `PostgreSQL database cluster dump complete`; it holds one `CREATE DATABASE`, 77 `COPY` blocks and the roles `aidss`, `trader_owner`, `trader_rw`, `trader_monitor`.
- Restore rehearsal: the dump was loaded into a throw-away `pgvector/pgvector:pg16` container (`--network none`, tmpfs data, random password, removed afterwards). Only 2 stderr lines, both "already exists" (the
  default `postgres` database and role). Row counts of all 77 base tables, live against restored, were identical (diff empty); examples: `public.users` 3 rows, every `trading.*` table 0 rows except
  `trading.alembic_version` 1 (the Trader has never traded, consistent with `HALTED`).

## Limits and risks

- The backup is on the same host as the database, so a lost or compromised host loses both. An off-host copy has not been made; it would put the dump (users table, password hashes of the roles, encrypted
  credential rows) on another machine and is the owner's call.
- No retention or rotation: the single file stays until the owner says otherwise.
- The restore rehearsal proves the dump loads and counts match on PostgreSQL 16; it does not exercise the application against the restored data.

## Next steps of the plan (each needs the owner's go-ahead)

1. Apply `isolate_analysis_role.sql` as `aidss` (creates `aidss_app`), then set passwords and record `AIDSS_APP_DATABASE_URL`.
2. Switch api and worker to `aidss_app`, unpublish port 5432 through the Compose override, rotate the superuser password.
3. Rollback path: `rollback_analysis_role.sql` and the restore of this dump.
