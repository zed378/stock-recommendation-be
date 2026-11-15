# 2026-11-15 — Runbook R15: updating the Trader image's dependencies

ADR-050 said someone has to own the routine for security updates to the hash lock, and nothing wrote it down. `docs/10-OPERATIONS/06-RUNBOOKS.md` now
has R15: when to update, how to regenerate `requirements-trader.lock` from `requirements-trader.in` inside `python:3.12-slim` (per-platform hashes), how to
move a single package (`--upgrade-package`), how to read the diff, the checks to run on the rebuilt image (`pip check`, module imports, migrations on a
throwaway PostgreSQL, `HALTED` start, the Trader suite inside the image's own dependency set), and that deploying is a separate, approved step.

Documentation only. The commands are the ones used on 2026-11-15 to build the lock (see `2026-11-15-s13-trader-dependency-lock.md` and
`2026-11-15-trader-image-own-dependencies.md`); `--upgrade-package` and the header-restoration step were not exercised. The base-image tag still floats.
