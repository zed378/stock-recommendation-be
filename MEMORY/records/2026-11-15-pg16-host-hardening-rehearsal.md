# 2026-11-15 — Host hardening rehearsal on the VM's PostgreSQL 16 (clone of `aidss`)

Run by the main agent over SSH, with the owner's go-ahead for the rehearsal only. The production steps
(`pg_dumpall`, create `aidss_app`, rotate the `aidss` password, close port 5432, `up -d`) have **not** been run and
still need the owner's explicit approval per step.

## What was run

On `stocks-postgres-1` (PostgreSQL 16.16, `pgvector/pgvector:pg16`), against a throwaway **clone** of the real
`aidss` database (337 MB), never the real database:

1. `pg_dump aidss | psql aidss_role_rehearsal` (no file on disk).
2. `deploy/trader/isolate_analysis_role.sql` as the superuser, then a random temporary password for `aidss_app`.
3. `alembic upgrade head` with the real analysis image `zed378/aidss-api:e7b3da3`, connecting as `aidss_app`.
4. `pytest -m postgres tests/trader/test_privileges_postgres.py` with owner, `trader_rw`, `aidss_app` and
   `trader_monitor` URLs, from the owner's machine over the published port.
5. Direct SQL as `aidss_app`.
6. `deploy/trader/rollback_analysis_role.sql`.
7. Cleanup: `DROP DATABASE ... WITH (FORCE)` and `DROP ROLE aidss_app` (the role is cluster-wide, so it would have
   outlived the scratch database).

## Measured results

| Step | Result |
|---|---|
| Clone | 11.4 s; 47 `public` and 30 `trading` tables, equal to the source |
| `isolate_analysis_role.sql` | 1.1 s; 47/47 `public` tables owned by `aidss_app`; role not superuser, no createdb, no createrole, no bypassrls |
| Analysis `alembic upgrade head` as `aidss_app` | exit 0 |
| `-m postgres` privilege tests | 6 passed, 0 skipped |
| `aidss_app` direct SQL | create/drop in `public` ok, `SELECT public.alembic_version` ok; `SELECT trading.audit_log`, `SELECT trading.credential`, `CREATE TABLE trading._x` all denied |
| `rollback_analysis_role.sql` | 1.2 s; 0 `public` tables not owned by `aidss` |
| Cleanup | role and database lists identical to before the run |

Pre-checks on the VM: Docker Compose v5.6.0 (supports `ports: !reset []`); every client of port 5432 is inside the
Docker network (api, worker, Trader at 172.22.0.x), none external; `pg_hba` has `host all all all scram-sha-256`; the
superuser `aidss` password is still the username; disk 150 GB free.

## Differences from production (stated, not hidden)

- The clone lacks the database-level `GRANT CREATE ON DATABASE ... TO trader_owner` (grants at that level are not in
  a dump), so the Trader's own `alembic upgrade head` failed on the clone with "permission denied for database". Not a
  defect of the plan: `aidss` already carries that grant, because migrations 0001 to 0008 ran there as `trader_owner`.
- No live traffic touched the clone. The analysis API and worker were **not** run against it as `aidss_app`; only
  alembic and direct SQL were. A query path that needs more than `public` read/write (for example pgvector use by the
  worker) is not covered.
- The 1.2 s rollback is the database side only. Restoring the connection URL, `up -d --no-build`, and service health
  were not timed.
- `docker-compose.yml` on the VM hard-codes `postgresql+psycopg://aidss:aidss@postgres:5432/aidss`. The production step
  must override that, not only add `AIDSS_APP_DATABASE_URL` to `~/.aidss-trader.env`.

## Still open

Everything that changes the host: the full `pg_dumpall` (the existing dumps are on the same disk), role creation and
password rotation, closing 5432, the override, and the post-change checks (login, worker, Trader `HALTED`, 5432 not
reachable from another machine). Also: SSH password rotation, the liveness monitor (Handoff G).
