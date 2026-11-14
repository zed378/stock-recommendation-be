# Runtime assembly and wiring (built, mock-tested, never run against an exchange)

**Date:** 2026-11-14
**Task:** assembly of T2 to T5 (no new task id)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/02-ARCHITECTURE/03`, `05`, `07`; `docs/05-MODULE-SPECIFICATIONS/03`, `04`, `08` to `10`; ADR-007, 022, 024, 027, 036, 041, 043, 047

---

## Hook

`aidss_trader run` now assembles a client, a notifier, a runtime loop, and the operator API, and the loop
decides, protects, syncs, and reconciles. **It has only ever run against the synthetic mock.** On a fresh
install it starts `HALTED`, every owner number is still unset, and the exchange URLs are unset in the Compose
file, so deploying this image trades nothing.

---

## What Changed

| Area | Detail |
|---|---|
| `runtime/loop.py` | One cycle: snapshot, breakers, exit monitor, order and fill sync, decisions, approvals expiry, notification retry, reconciliation. Each step is isolated; a failure never skips a protective one |
| Decisions | Only while `RUNNING`, with a full snapshot, every required limit set, a registered strategy version, a configured liquidity filter, and (for sends) a clean reconciliation. `PAPER` intents are recorded and labelled, never sent; `APPROVAL` entries become cards; `AUTO` and signal exits go through the Risk Engine and the order manager |
| Protection | Stops come from the intent that opened the position and never loosen; a stop sells MARKET under the EMERGENCY profile, at most one at a time; with no price the monitor runs blind and reports the position unprotected, once |
| Breakers | HALT or CANCEL through the kill switch, only from `RUNNING`; permissions, clock, UNKNOWN order, reconciliation difference, loss limits, stale data (age of the last good snapshot against the owner's freshness limit) |
| `runtime/accounting.py` | Positions, realised loss since local midnight WIB, consecutive losses, drawdown, all from stored LIVE fills and equity snapshots; PAPER rows never count |
| `runtime/settings_store.py`, API | Allowlist, liquidity filter (OQ-8), strategy parameters (OQ-11): audited, loosening needs a step-up, a parameter change registers a new version in PAPER |
| Assembly | `build_client`, `build_runtime`, `build_api`; the credential is read per signature; the API is served only when the analysis API URL is set; Compose passes no exchange URL |
| Migration `0005_runtime` | `trader_setting`, `equity_snapshot` (PostgreSQL grants not run) |

## Bugs found by running it

- `check_clock` measured around the throttle's wait, so a drained bucket looked like clock skew (a real
  production defect, not a mock artefact). It now times only the wire.
- A transient refusal (no clean reconciliation yet) used up the candle's intent identity forever; the loop now
  waits before deciding instead.
- A price outage skipped the exit monitor entirely because it needed a snapshot; it now runs blind.
- Approval hashes and rebuilt intents differed after a database round trip (SQLite stores Numeric as a float);
  both now quantise to 8 decimals via `intent_from_row`.
- The watchdog alert key carried a growing cycle count and re-alerted every cycle.
- While halted the loop still created cards and paper records; it now decides nothing.
- I ran `ruff format src` once and reformatted 78 analysis-platform files; they were reverted with
  `git checkout -- src/aidss` before anything was committed. Trader paths only from now on.

## Not Done, Not Verified

- **Never run against an exchange**, a PostgreSQL database, or the Docker image. Nothing was observed live.
- **PAPER lifecycle is not built:** paper intents are recorded but no paper fills, paper stops, or paper
  positions exist, so the promotion gate "paper trades" cannot yet be met from real running.
- The liquidity filter derives 24-hour volume from stored candles (volume x close over six 4H candles) because
  the connector has no volume call; this approximation is mine, not documented by Indodax.
- Candle freshness uses two timeframes and the entry-wait on reconciliation is a structural rule, not an owner
  number; the throttle headroom (half the documented limits) is an engineering margin.
- A `SUBMITTING` order older than 30 seconds is treated as `UNKNOWN`. The 30 seconds is my choice.
- Promotion thresholds are still not stored, so every promotion stays blocked; the credential, limits editor,
  and strategy list screens in the UI do not exist; no front-end tests.
- ADR-047 is `proposed`. The Compose service name and port 8001 for the nginx proxy are unverified.
