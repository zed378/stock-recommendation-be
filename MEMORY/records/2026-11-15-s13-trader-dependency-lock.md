# 2026-11-15 — S13: hash-pinned dependencies for the Trader image (ADR-050, option 1)

Chosen by the owner on 2026-11-15 (hash lockfile). Implemented in the repository; **no image was built for deployment and
nothing was deployed**. The VM still runs `aidss-trader:e410ab7`, built with version ranges.

## What changed

- `requirements-trader.lock`: 44 packages with sha256 hashes, generated inside `python:3.12-slim` by
  `uv pip compile pyproject.toml --generate-hashes --python-version 3.12 --python-platform linux`. The regeneration command is in
  the file's header.
- `Dockerfile.trader`: installs with `pip install --require-hashes --no-deps -r requirements-trader.lock`; the unpinned
  `pip install --upgrade pip` is removed; the package is not pip-installed (that would fetch an unpinned `setuptools`),
  its source is on `PYTHONPATH=/app/src`.
- `tests/trader/test_security_s1_s17.py`: the strict `xfail` `test_s13_dependencies_are_pinned` is replaced by three tests
  (hashes on every package; the Dockerfile uses only the lock with `--require-hashes --no-deps`; the lock satisfies
  `pyproject.toml`). 28 pass in that file.
- ADR-050 now `accepted`; the BACKLOG row is removed; `PROGRESS.md` and `CLAUDE.md` updated (Trader + architecture + routing:
  513 passed, 7 deselected, no xfail; Vitest 74).

## Evidence

- A local build from the lock succeeded; `pip check` reports no broken requirements; `python -m aidss_trader --help` and the
  imports work.
- `pip freeze` of the new image against the deployed `e410ab7`: same 44 package versions; the only difference is the `aidss`
  package itself. Adopting the lock therefore changes no running dependency.
- Hash enforcement: with every hash of one package altered, the build fails with `THESE PACKAGES DO NOT MATCH THE HASHES` (exit 1).
  An earlier attempt that altered only one of a package's two hashes passed, which is expected: pip accepts a file when any listed
  hash matches.

## Not verified / left open

- The new image was not run as the Trader against a database (no `HALTED` start, no healthcheck loop); only imports and `--help`.
- The base image is still the floating tag `python:3.12-slim`, so builds are not byte-reproducible at the OS layer.
- The image still installs everything in `[project].dependencies` (pandas, numpy, curl_cffi and others) although the Trader may
  need fewer; not changed here.
- The lock covers Linux and Python 3.12 only; on Windows or another Python it must be regenerated in a container.
- Someone must own the update routine for security fixes.
