# Host hardening plan, `aidss_app` role isolation, and master-key re-entry runbook (prepared, awaiting owner approval)

**Date:** 2026-11-15
**Task:** Track 1 (host hardening plan, ADR-021 role isolation SQL, master-key re-entry runbook, ADR-040 backup note)
**Author:** Antigravity (AI agent), working with the project owner
**Spec refs:** `docs/09-SECURITY-PRIVACY/02-SECRETS-AND-KEY-ROTATION.md`; `docs/10-OPERATIONS/04`, `06`; ADR-014, 021, 029, 040

---

## Hook

Prepared the SQL migration (`deploy/trader/isolate_analysis_role.sql`), rollback (`deploy/trader/rollback_analysis_role.sql`), Compose override (`deploy/trader/docker-compose.trader.yml`), privilege tests (`tests/trader/test_privileges_postgres.py`), and runbooks (`R10`, `R13`) to close PostgreSQL host port 5432, rotate the superuser password, move the analysis API and worker onto a non-superuser role (`aidss_app`) with zero access to `schema trading`, and document the master-key re-entry procedure. **Not yet executed on the VM (`10.1.200.13`)**: execution awaits the owner's explicit approval and SSH password.

---

## What Changed

| Area | Detail |
|---|---|
| `deploy/trader/bootstrap.sql` | Adds role `aidss_app` (`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`) with `USAGE, CREATE ON SCHEMA public` |
| `deploy/trader/isolate_analysis_role.sql` | Creates/hardens `aidss_app`, ensures `vector` extension exists, transfers ownership of tables, sequences, views, and enum types in `schema public` ONLY to `aidss_app` (so `api` startup's `alembic upgrade head` works without superuser), and revokes all privileges on `schema trading` from `PUBLIC` and `aidss_app` |
| `deploy/trader/rollback_analysis_role.sql` | Returns ownership of `schema public` objects back to `aidss` if rollback is needed |
| `deploy/trader/docker-compose.trader.yml` | Overrides `postgres.ports: !reset []` (closing host port 5432 exposure) and overrides `api` and `worker` `AIDSS_DATABASE_URL` to `${AIDSS_APP_DATABASE_URL}` without editing root-owned `~/stocks/.env` or `~/stocks/docker-compose.yml` |
| `tests/trader/test_privileges_postgres.py` | Adds `test_analysis_app_role_owns_public_but_cannot_access_trading_schema` (`AIDSS_TRADER_TEST_APP_URL`) and `test_monitor_role_reads_heartbeat_only` (`AIDSS_TRADER_TEST_MONITOR_URL`) |
| `docs/09-SECURITY-PRIVACY/02-SECRETS-AND-KEY-ROTATION.md` & `docs/10-OPERATIONS/06-RUNBOOKS.md` | Writes exact master-key generation, path (`~/.aidss-trader-master.key`, mode `0600`), and step-by-step re-entry procedure (`R10`) plus host PostgreSQL hardening procedure (`R13`) |
| `docs/10-OPERATIONS/04-BACKUP-RESTORE-AND-RECOVERY.md` | Records that `~/aidss-pre-trader-*.sql.gz` sits on the same host disk (`10.1.200.13`, accepted under ADR-040, manual off-host copy needed) |

## Execution Plan on `10.1.200.13` (Awaiting Owner Approval)

1. **Pre-check active connections on port 5432** before unpublishing:
   - Inspect `pg_stat_activity` (`WHERE client_addr IS NOT NULL`) and host sockets (`ss -tnp 'sport = :5432'`) to confirm no external stack outside `stocks-*` connects to `stocks-postgres-1`.
2. **Take a fresh pre-change backup**:
   - `docker exec stocks-postgres-1 pg_dumpall -U aidss | gzip > ~/aidss-pre-hardening-$(date +%Y%m%d-%H%M%S).sql.gz` (chmod 0600).
3. **Rehearse on a scratch database first**:
   - `CREATE DATABASE aidss_role_rehearsal`, run `bootstrap.sql`, `isolate_analysis_role.sql`, Trader migrations `0001..0006`, and `pytest -m postgres tests/trader/test_privileges_postgres.py` with `AIDSS_TRADER_TEST_OWNER_URL`, `AIDSS_TRADER_TEST_RW_URL`, `AIDSS_TRADER_TEST_APP_URL`, and `AIDSS_TRADER_TEST_MONITOR_URL`, then `DROP DATABASE aidss_role_rehearsal`.
4. **Apply to `aidss` database and rotate passwords**:
   - Run `isolate_analysis_role.sql` on `aidss`.
   - Set a random cryptographic password for `aidss_app` and rotate the `aidss` superuser password (`ALTER ROLE ... PASSWORD`).
   - Add `AIDSS_APP_DATABASE_URL` to `~/.aidss-trader.env` (mode `0600`).
5. **Apply Compose override via stdin** (closing host port 5432 and switching `api`/`worker` to `aidss_app`):
   - `set -a; . ~/.aidss-trader.env; set +a; docker compose -f docker-compose.yml -f - up -d --no-build < deploy/trader/docker-compose.trader.yml`
6. **Verify**:
   - `docker ps` shows `0.0.0.0:5432` is gone, all four `stocks-*` containers are healthy, `GET /health` returns 200, `aidss_app` cannot `SELECT` from `trading.credential`, and the Trader remains `HALTED`.

## Not Verified

- **Not executed on `10.1.200.13` yet**: awaits the owner's approval of the migration/rollback plan above and the SSH password for `infra@10.1.200.13`.
- The two new PostgreSQL privilege tests (`test_analysis_app_role_owns_public_but_cannot_access_trading_schema` and `test_monitor_role_reads_heartbeat_only`) have not been run against a live PostgreSQL instance yet.
- The SSH password for `infra@10.1.200.13` was shared in chat earlier and must still be rotated by the owner.
