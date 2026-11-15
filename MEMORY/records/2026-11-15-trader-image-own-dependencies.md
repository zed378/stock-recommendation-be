# 2026-11-15 — The Trader image installs only the Trader's own dependencies (ADR-053)

Asked for by the owner after the S13 lock (ADR-050) listed it as a separate decision. In the repository only: **no image was pushed and
nothing was deployed**. The VM still runs `aidss-trader:e410ab7`, built from version ranges.

## Finding

The lock built for S13 covered all of `[project].dependencies`, 44 packages. A static scan of `src/aidss_trader`, `alembic_trader` and
`deploy` shows the Trader imports only cryptography, fastapi, httpx, pydantic, pydantic-settings, sqlalchemy and uvicorn, plus alembic for
migrations and the psycopg driver. pandas, numpy, curl_cffi, bcrypt, PyJWT, croniter, pgvector and email-validator are never imported (the
Trader checks callers by asking the analysis API, so it has no JWT code of its own), and `uvicorn[standard]` pulled in uvloop, httptools,
websockets, watchfiles and PyYAML for a service with no WebSocket and settings that read only the environment (`env_file=None`).

## What changed

- `requirements-trader.in` (new): the nine direct requirements, same lower bounds as `pyproject.toml`, plain `uvicorn`.
- `requirements-trader.lock`: regenerated from it with `uv pip compile --generate-hashes` inside `python:3.12-slim` (command in its header).
  44 packages become 28; all 28 keep the versions they had; none added. Removed: bcrypt, croniter, curl-cffi, dnspython, email-validator,
  httptools, numpy, pandas, pgvector, pyjwt, python-dateutil, pyyaml, tzdata, uvloop, watchfiles, websockets.
- `tests/trader/test_security_s1_s17.py`: the single "lock satisfies pyproject" test is replaced by three: the lock satisfies every direct
  requirement; `requirements-trader.in` has the same bounds as `pyproject.toml`; and the Trader imports nothing outside the lock (a probe
  `import pandas` in `src/aidss_trader` failed it by name; the probe was removed). 30 pass in that file.
- `Dockerfile.trader` comment, ADR-053 (accepted), ADR-050's implication line.

## Evidence (local, throwaway)

- Image size 593 MB (44-package lock) to 291 MB. `pip check`: no broken requirements. All 73 `aidss_trader` modules import.
- Against a throwaway `pgvector/pgvector:pg16` on a private Docker network: `alembic upgrade head` as `trader_owner` reached
  `0008_indexes_idempotency` with 30 tables in `trading`; the Trader, run as `trader_rw` with a generated master key and
  `AIDSS_TRADER_ANALYSIS_API_URL` pointing at an unreachable address, started `HALTED`, was `healthy`, `healthcheck` exited 0,
  `/trader/v1/status` answered `401` with `X-Frame-Options: DENY` and the CSP (with and without a bearer token, which is the
  fail-closed answer when the analysis API cannot be reached), cycles ran, and the log held no traceback.
- Suite: Trader + architecture + routing 515 passed, 7 deselected, no xfail; `ruff` clean.

## Suite inside the slim image's dependency set (added after the first commit)

The Trader tests ran inside `aidss-trader-s13:slim` (28 locked packages plus `pytest` and its own dependencies, 34 in all; no pandas, numpy,
bcrypt, PyJWT or curl_cffi). The repository was mounted read-only and `tests/trader` copied into a scratch directory so the analysis platform's
`tests/conftest.py` (which imports `aidss.main` and needs bcrypt) was not loaded. Result: **461 passed, 2 failed, 7 deselected**.

- The two failures need the `git` binary, which the slim image does not have, and have nothing to do with dependencies:
  `test_livecheck.py::test_it_refuses_directories_inside_a_git_repository` and
  `test_security_s1_s17.py::test_s17_no_tracked_file_contains_a_key_shaped_secret` (it runs `git ls-files`). They pass in the full suite.
- Left out: `test_guards.py` and `test_trader_role.py`, the only two files in `tests/trader` that import the analysis platform (`aidss.*`); they test
  the platform's side (guards, the RBAC mapping), not the Trader's runtime.
- Not covered: the `-m postgres` tests, and `tests/test_architecture_constraints.py` / `tests/test_frontend_routing.py` (static, no dependency question).

## Not verified / left open

- Not deployed, so the running image still carries the 44 packages. The first real exercise is the next deploy.
- uvicorn now runs on the plain asyncio loop instead of uvloop. Expected to be irrelevant at this traffic, not measured.
- The smoke test used no real analysis API, no exchange, and a database with an empty ledger. Superuser-free privileges were exercised
  (owner for migrations, `trader_rw` for the run), but `trader_monitor` and the PostgreSQL privilege tests were not re-run on this image.
- Two setup slips while testing, both of my own and not of the image: the first migration attempt ran as the superuser and left the
  `trading` schema owned by it, so the second attempt as `trader_owner` failed until the schema was dropped; and the roles had to exist first.
