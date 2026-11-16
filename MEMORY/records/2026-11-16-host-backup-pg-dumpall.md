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

---

## Step 1 applied: role `aidss_app` created on production (2026-11-16, after the owner's go-ahead)

Rehearsal first, on the VM, because the earlier rehearsals ran on a local PostgreSQL 18: `rehearse_isolation.sh stocks-postgres-1 aidss aidss` against a scratch clone of `aidss` on the production PostgreSQL 16 (clone 12s, isolation under 1s,
rollback under 1s; `aidss_app` not superuser, owns every `public` table, `trading.audit_log` denied for it, DDL in `public` allowed). The scripts were placed in `~/rh` for the run and the directory, the scratch database and the temporary role were removed afterwards.

Applied for real, as superuser `aidss` in database `aidss`, with `ON_ERROR_STOP=1` (the file is one transaction): `deploy/trader/isolate_analysis_role.sql`. Then a random 48-hex-character password was set through stdin
(`ALTER ROLE aidss_app PASSWORD`, never on a command line) and `AIDSS_APP_DATABASE_URL=postgresql+psycopg://aidss_app:<password>@postgres:5432/aidss` was appended to `~/.aidss-trader.env` (mode `0600`). No password appears in this repository, the log or the shell history.
The helper scripts and the SQL copy on the host were deleted.

Verified after: connecting as `aidss_app` over TCP works and reads `public.users` (3 rows); `select count(*) from trading.audit_log` fails with `permission denied for schema trading`; the role is `rolsuper=f, rolcreatedb=f, rolcreaterole=f, rolbypassrls=f`;
no `public` table has an owner other than `aidss_app`; all containers stayed healthy (nothing was restarted), Trader healthcheck exit 0, `trading_state` `HALTED`, `/api/health` 200.

Not changed on purpose: `api` and `worker` still connect as the superuser `aidss` (`docker-compose.yml` on the host carries `AIDSS_DATABASE_URL: postgresql+psycopg://aidss:aidss@postgres:5432/aidss`, a literal weak password, which the next step replaces through the override),
port 5432 is still published, and the superuser password is unchanged. Until step 2 the isolation is prepared, not in force.

Rollback of step 1: run `rollback_analysis_role.sql` as `aidss` (returns ownership of `public` objects to `aidss`, rehearsed at under 1s on the clone), then `DROP ROLE aidss_app` once nothing connects as it, and remove the `AIDSS_APP_DATABASE_URL` line from `~/.aidss-trader.env`. The pre-change dump is `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz`.

Next (needs the owner's go-ahead): step 2, switch `api` and `worker` to `aidss_app` through the override, unpublish port 5432 (`ports: !reset []`), then rotate the superuser password; check the pre-step `pg_stat_activity` for any outside client first (R13, point 1).

---

## Step 2 applied: api and worker on `aidss_app`, port 5432 closed, superuser password rotated (2026-11-16, after the owner's go-ahead)

Pre-check (R13 point 1): `pg_stat_activity` showed only Compose-network clients (`172.22.0.x`: api, worker, trader), none from outside. Three sub-steps, each verified before the next, all through the stdin Compose override
(`up -d --no-build <service>`, env from `~/.aidss-trader.env`); `docker-compose.yml` on the host was not edited.

- **2a, api and worker as `aidss_app`:** override sets `AIDSS_DATABASE_URL: ${AIDSS_APP_DATABASE_URL}` for both; only `api` and `worker` were recreated. `docker compose config` resolved both to `aidss_app`.
  After: `pg_stat_activity` shows `aidss_app` for both, `trader_rw` for the Trader, no `aidss` connection; api healthy, `/health` 200, worker started with the leader lease; no error in the api log.
- **2b, port 5432 closed:** override adds `postgres: ports: !reset []` (as in `deploy/trader/docker-compose.trader.yml`); `postgres` was recreated (same volume, data kept). Before: a TCP connect from the owner's workstation to `10.1.200.13:5432` succeeded;
  after: `Connection refused`, `ss -ltn` shows nothing on 5432. The Trader, api and worker reconnected on their own; the api's realtime listener logged one reconnect warning at the restart and was listening again within a second.
- **2c, superuser password:** `ALTER ROLE aidss PASSWORD` with a random 48-hex-character value through stdin, stored only in `~/.aidss-pg-superuser` (mode `0600`, outside the file Compose reads). From another container the old password `aidss` is now refused
  (`password authentication failed`); the new one works. Administration through `docker exec stocks-postgres-1 psql -U aidss` is unchanged (the image's `pg_hba.conf` trusts the local socket and `127.0.0.1` inside the container).

Verified after all three: containers healthy, Trader healthcheck exit 0 and `trading_state` `HALTED`, `/`, `/login` and `/api/health` answer 200.

Still open, not part of this step:
- The host's `docker-compose.yml` keeps `AIDSS_DATABASE_URL: ...aidss:aidss@...` and `POSTGRES_PASSWORD` defaults for a fresh start without the override; with the password rotated that URL no longer works, so `up` **without** the stdin override would start api and worker
  that cannot connect. The deploy recipe must keep using the override (it already does); the base file on the host should be fixed by the owner or the main agent.
- Other ports published on the host: api `7153` and frontend `5173` (reachable directly, bypassing the reverse proxy); not examined here.
- The superuser password and `AIDSS_APP_DATABASE_URL` are single copies on the host; the backup `~/aidss-backups/pg_dumpall-20261116T100117Z.sql.gz` is on the same host.
- Not exercised: a logged-in user flow and a worker job run as `aidss_app` after the change (health, connections and logs only).

Rollback of step 2: set `AIDSS_DATABASE_URL` back to the superuser in the override (using the stored superuser password) and recreate `api` and `worker`; re-add `ports: ["5432:5432"]` to bring the published port back; the dump is the last resort.
