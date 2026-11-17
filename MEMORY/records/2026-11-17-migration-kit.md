# Migration kit: moving AIDSS to another host (2026-11-17)

The owner said the project will be moved elsewhere some day and asked for it to be made ready. Nothing was moved. What exists now:

## Inventory of what is tied to the current host (read-only, 2026-11-17)

Compose project `stocks` on `10.1.200.13` (Docker 29.8.2, Compose v5.6.0, Ubuntu, UTC, NTP active). Data: `stocks_postgres_data` 509 MB (about 71 MB as a gzipped dump), `stocks_storage_data` empty (4 KB, 0 files). Host files: `~/stocks/.env` (JWT secret and settings), `~/.aidss-trader.env`
(database URLs), `~/.aidss-trader-master.key` (44 bytes), `~/.aidss-pg-superuser`, `/etc/cloudflared/token` (root, 600; the public site enters through the host `cloudflared`), netbird as a snap service, backups under `~/aidss-backups/`.
The published images are `linux/amd64` only. The hand-edited compose file on the host (an older copy of the development file, root-owned) was the only description of the production stack.

## Added

- `deploy/production/docker-compose.production.yml`: the whole stack (postgres, api, worker, frontend, trader), project name `stocks`, one `.env`, no override on standard input. Images are required variables (no `latest` default), the database URLs, the JWT secret and `POSTGRES_PASSWORD` have no default,
  only the frontend is published (`127.0.0.1:5173`), the Trader gets no exchange URL. `production.env.example` lists the names with required ones left empty, so an unfilled copy is refused.
- **Equivalence proof on the real host** (nothing started or changed): the file's effective configuration, built from an `.env` made of the two files that exist today, was compared with the running stack (base file plus override) for all five services over image, restart policy, user, read-only, ports, expose, volumes, secrets, `depends_on` with conditions,
  health check, command, security options, tmpfs and a hash of the whole environment: **0 differences**. The temporary files on the host (including the combined `.env`) were shredded and removed.
- `preflight.sh` (new host, read-only; machine, NTP, architecture, disk, port, the `.env` read as text and never sourced, key file mode and size, compose resolves, images found in the registry), `restore.sh` (a `pg_dumpall` from standard input into a fresh PostgreSQL container;
  refuses when any application container runs, even with `--force`, and when the database already has tables; tolerates only "already exists"), `fingerprint.sh` (row counts, versions, roles, trading state, audit head, and 12-hex hashes of the JWT secret and master key, so equality is shown without printing a secret).
- `docs/10-OPERATIONS/09-MIGRATION-RUNBOOK.md`: what moves and what does not, the Trader's special cases (one writer, `HALTED`, source IP at the exchange, readable credentials, clock), preparation, the cutover in phases with rollback, the cleanup and rotation afterwards, variants. Pointers added to `02-DEPLOYMENT-ARCHITECTURE.md` (whose "Current Deployment" paragraph was stale) and `04-BACKUP-RESTORE-AND-RECOVERY.md`.
- `tests/trader/test_migration_kit.py` (8 tests, `-m postgres`, needs Docker): a source cluster with roles, the `trading` schema and Alembic tables is dumped with `pg_dumpall` and restored into an empty one; the two fingerprints are equal; role password hashes come from the dump; a second restore is refused; a running application container stops a restore even with `--force`;
  an error other than "already exists" fails it; the JWT hash can come from the `.env`; the compose file refuses an unfilled `.env`, resolves a filled one, and publishes only `127.0.0.1:5173`.

## Verified on the real host

`fingerprint.sh` ran read-only against production (PostgreSQL 16.16, pgvector 0.8.6, Alembic heads, 5 roles, 80-odd tables, `trading_state` `HALTED`); `preflight.sh` ran there with a dummy `.env` and gave the expected two FAILs (port 5173 in use, `stocks-*` containers running) and, with a deliberately broken `.env`, the FAILs for a `latest` Trader image, the superuser URL and mode 644.
Also on the way: the old plaintext dumps in the home directory (`aidss-pre-*.dump`, two were mode 664) were set to mode 600.

## Not verified

A restore of the real dump, a real second host, the Cloudflare tunnel move, any timing (the runbook's 15 to 30 minutes is an estimate), the Indodax source-IP rule (no key stored yet), a build for ARM. The local rehearsal used synthetic data in throw-away containers. Recommended before the real move: one full rehearsal on a scratch host with the real dump, writing the timings into the runbook.
`deploy/trader/backup_offhost.sh` (stage 11, the encrypted off-host copy) was not yet available; the runbook gives the manual streaming command for it.
