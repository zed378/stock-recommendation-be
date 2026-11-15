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

## Not verified / left open

- Not deployed, so the running image still carries the 44 packages. The first real exercise is the next deploy.
- uvicorn now runs on the plain asyncio loop instead of uvloop. Expected to be irrelevant at this traffic, not measured.
- The smoke test used no real analysis API, no exchange, and a database with an empty ledger. Superuser-free privileges were exercised
  (owner for migrations, `trader_rw` for the run), but `trader_monitor` and the PostgreSQL privilege tests were not re-run on this image.
- Two setup slips while testing, both of my own and not of the image: the first migration attempt ran as the superuser and left the
  `trading` schema owned by it, so the second attempt as `trader_owner` failed until the schema was dropped; and the roles had to exist first.
