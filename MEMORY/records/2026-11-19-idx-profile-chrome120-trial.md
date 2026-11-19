# IDX browser profile `chrome120`: a trial the owner asked for (2026-11-19)

Another agent left a one-line, uncommitted change in `src/aidss/config.py` (`idx_impersonate` default `chrome` to `chrome120`) while trying to fix the IDX 403. The owner asked to build and deploy it.

Finding before building: the stack never uses that code default. `docker-compose.yml` (repo, production kit and the host's copy) passes `AIDSS_IDX_IMPERSONATE: ${AIDSS_IDX_IMPERSONATE:-chrome}`, so the worker always received `chrome`. A rebuild alone would have changed nothing. What takes effect is the environment variable, so that is what was deployed; no image was built.

Done: repo defaults aligned to `chrome120` (code default, both compose files, both env examples, README row); on the VM `AIDSS_IDX_IMPERSONATE=chrome120` appended to `~/stocks/.env` (`infra:infra 600`, backup `~/stocks/.env.bak-idx-20261119`) and only the worker recreated with `--no-deps` (it is the only caller of IDX); verified `chrome120` inside the worker, the other containers untouched and healthy.
This is the same kind of lever as the `chrome136` trial of 2026-11-18, which was reverted at the owner's request; ADR-057 does not adopt browser-profile changes as the fix, because the cause is more likely the datacenter address than the profile. It is a trial and the result is not known: the next IDX job decides (`market.trading_summary` runs about 11:00 UTC, `fundamentals.refresh` and `issuers.sync` on the scheduler tick).
Revert: restore the `.env` backup (or delete the line) and recreate the worker; set the repo defaults back to `chrome`.
