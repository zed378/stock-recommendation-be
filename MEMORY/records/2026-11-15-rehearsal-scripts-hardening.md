# 2026-11-15 — Review fixes to the rehearsal scripts (`rehearse_isolation.sh`, `rehearse_restore.sh`)

Main-agent review of Stage 4 Task L found three problems before the scripts were ever run on the VM.

1. **Dump readable by other users.** Both scripts wrote the dump to `/tmp` with the default umask. With `--full` it
   holds password hashes and encrypted credentials, and the VM is a shared host. Both scripts now set `umask 077`
   before the first `pg_dump`.
2. **A generic failure counted as "denied".** `rehearse_isolation.sh` treated any non-zero psql exit as proof that
   `aidss_app` cannot read `trading.audit_log`. It now requires the message `permission denied`; anything else
   (bad connection, missing schema) fails the run.
3. **Relative paths on a host with no checkout.** The scripts read `deploy/trader/*.sql`; the VM has no repository
   checkout and new directories are not allowed there. `06-RUNBOOKS.md` now says to run them from a copy of
   `deploy/trader/` placed for the duration of the run and removed afterwards.

Tests: `tests/trader/test_rehearsal_scripts.py` gained a check that `umask 077` precedes the first `pg_dump`
command and that the denial is matched on the message (5 passed).

Verified on a throwaway local `pgvector/pgvector:pg18` container (removed afterwards): the success path exits 0 with
the scratch database and role gone and no dump left in `/tmp`; with the `trading` schema absent the run now exits 1
and the cleanup still runs. Not verified: a run on the VM's PostgreSQL 16 (nothing was run there), and the `umask`
effect on a dump file's actual mode (only the script text and the clean `/tmp` afterwards were checked).
