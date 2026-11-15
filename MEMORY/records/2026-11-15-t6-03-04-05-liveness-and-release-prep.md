# T6-01 review packet, T6-03 restore rehearsal script, T6-04 host liveness monitor, and T6-05 release checklist evidence

**Date:** 2026-11-15
**Task:** T6-01 (independent review packet), T6-03 (prepared), T6-04 (built & fake-receiver tested), T6-05 (draft populated with evidence)
**Author:** Antigravity (AI agent), working with the project owner
**Spec refs:** `docs/10-OPERATIONS/04`, `05`, `06`; `docs/09-SECURITY-PRIVACY/00`; `docs/11-TESTING-QUALITY/04` (A13); `docs/12-DELIVERY-PLAN/05`; ADR-039, ADR-040, ADR-043

---

## Hook

Completes the non-owner-gated deliverables of Phase T6:
1. **T6-04 (`deploy/trader/check_liveness.py`):** Out-of-process host liveness monitor that connects with read-only role `trader_monitor` (`SELECT ON trading.lease` only), reads the Telegram bot token and chat ID from a root-only host file (`/root/.aidss-monitor-telegram.env`, mode `0600`), and alerts Telegram directly when the `trader` lease row is missing or older than `15` seconds (ADR-039, ADR-043). Includes state-file cooldown (`--state-file`, `--cooldown-s`) and full secret redaction on stdout/stderr/exceptions.
2. **Acceptance A13 (`tests/trader/test_liveness_monitor.py`):** End-to-end test against a local fake Telegram HTTP server verifying fresh heartbeats, stale/missing heartbeats, cooldown suppression and recovery, secret redaction on HTTP 500 failure, and A13 (stopping the Trader with an open position triggers the out-of-process Telegram alert, and on restart `ExitMonitor` evaluates and fires the `MARKET` stop exit first).
3. **T6-03 (`deploy/trader/rehearse_restore.sh` & Runbook R14):** Non-destructive restore rehearsal script that dumps `schema trading`, restores into a temporary scratch database (`aidss_restore_rehearsal_<ts>`), verifies table row counts and `trader_rw`/`trader_monitor` privilege boundaries, prints elapsed seconds, and drops the scratch database on exit.
4. **T6-01 (`docs/09-SECURITY-PRIVACY/00-THREAT-MODEL.md`):** Independent security review packet prepared for the reviewer chosen by the owner, enumerating the exact files, OpenAPI route checks, `S1`–`S17` results, and open items (`S13`, `S15`, Jalur 1 host execution).
5. **T6-05 (`docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md`):** Populated with test names and record references; only strictly automated, completed mock checks are marked `[x]`, while every owner-led decision, number, live check, and VM drill remains `[ ]`.

---

## What Was Verified

- `python -m pytest tests/trader/test_liveness_monitor.py -q` — **4 passed**:
  - `test_fresh_heartbeat_sends_no_alert`
  - `test_stale_or_missing_heartbeat_alerts_telegram_directly_with_cooldown`
  - `test_cli_main_reads_token_file_and_redacts_secrets_on_failure`
  - `test_acceptance_a13_stop_trader_with_open_position_alerts_and_evaluates_stops_first_on_restart`
- `python -m pytest tests/trader tests/test_architecture_constraints.py -q` — full hermetic Trader & architecture suite passes.
- `ruff check src/aidss_trader tests/trader alembic_trader deploy/trader/check_liveness.py` — `All checks passed!`.

---

## What Was Not Determined / Not Executed

- **Host cron installation (`T6-04`):** `deploy/trader/check_liveness.py` was **not** installed or scheduled on `10.1.200.13` (per owner instructions: do not install on the host without explicit owner approval, and while the Trader is intentionally idle/unconfigured a scheduled check would alert).
- **Owner-led VM drills (`T6-03`):** `deploy/trader/rehearse_restore.sh`, master-key re-entry (`R10`), and live VM CLI/UI kill-switch drills have not been run on `10.1.200.13` yet.
- **Independent security review (`T6-01`) and `AUTO` readiness (`T6-05`):** Owner-led; all corresponding checklist boxes in `docs/12-DELIVERY-PLAN/05-RELEASE-CHECKLIST.md` remain unchecked.
