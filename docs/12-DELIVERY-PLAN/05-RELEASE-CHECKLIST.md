# 05 — Release Checklist

| | |
|---|---|
| **Status** | Draft with mock-test evidence populated, 2026-11-15 (owner-led items remain unchecked) |
| **Owner** | Technical Lead, Risk Engineer, Owner |
| **Decided by** | ADR-003, ADR-020 |

Each item is checked with evidence (a named test, a record, or an owner statement). An unchecked item blocks
the stage named in its heading. Items requiring an owner action, owner number, live exchange call, or host drill
are left `[ ]` until the owner runs and records them.

## Before Any Live Read-Only Contact (T2-07)

- [ ] The owner has generated a **Read-only** TAPIv2 key and provided it for the check, by a means that
      avoids the repository and chat history. *(Owner-led; script prepared in `src/aidss_trader/livecheck/` — see `MEMORY/records/2026-11-15-t2-07-live-check-prepared.md`.)*
- [x] The connector's allowlist guard passes (no write method reachable from the check). *(Verified on mock: `tests/trader/test_livecheck.py`, `tests/trader/test_guards.py` — 24 tests pass.)*
- [ ] The `live_readonly` run is explicit and confirmed; it logs no secret. *(Mechanism verified on mock in `tests/trader/test_livecheck.py`; live execution against Indodax is owner-led and not yet run.)*
- [ ] Differences found are recorded in `06-INTEGRATIONS/11` and the mock corrected. *(Awaits T2-07 live run.)*

## Before the First `APPROVAL` With Real Money (T5-06)

**Code and tests**
- [x] All guard tests pass (`11/00`), by name, in the record. *(`tests/trader/test_guards.py`: import boundary, no-withdrawal client, no-float money, non-empty package tree.)*
- [x] The analysis platform's architecture test passes unmodified. *(`tests/test_architecture_constraints.py`: 8 passed, file untouched.)*
- [ ] Contract, integration, acceptance A1 to A22, and security S1 to S17 pass on the mock. *(Mock tests pass in `tests/trader/test_connector_contract.py`, `test_runtime_wiring.py`, `test_t5_operator_surface.py`, `test_j4_features.py`, `test_liveness_monitor.py` [A13], and `test_security_s1_s17.py` [25 pass]; **remains unchecked** because `S13` dependency lockfile is `xfail` and `S15` self-role clause diverges — see `MEMORY/records/2026-11-15-t6-security-and-resilience-tests.md`.)*
- [ ] Resilience R1 to R11 pass. *(`R1`–`R4` and `R6`–`R11` plus `P1`–`P4`, `P6`, and PAPER soak pass on the mock in `tests/trader/test_resilience_r1_r11.py`; **remains unchecked** because `R5` [frozen price feed returning identical value with HTTP 200] and `P5` [dashboard query plans] are not yet met — see `MEMORY/records/2026-11-15-t6-security-and-resilience-tests.md`.)*
- [ ] Image scan, secret scan, and a check that the image has no torch, no tests, no secrets, and no configuration values. *(Tracked-file secret scan passes in `test_s17_*` and `Dockerfile.trader` verified without torch on VM deploy `2026-11-15-first-deploy.md`; container vulnerability/layer scan not yet recorded.)*
- [ ] The Trader image repository is **private** (ADR-030). Copies pulled while it was public are assumed seen, so no secret or owner number was ever in them. *(Owner action on Docker Hub `zed378/aidss-trader` before T5-06.)*

**Controls**
- [ ] Every risk limit is **set by the owner** and recorded (OQ-9). None is a default. *(Owner-led via `/trader/limits`; currently all unset and trading disabled.)*
- [ ] The kill switch has been drilled on the mock, from the UI, the API, and the command line. *(API and service tiers verified in `tests/trader/test_t4_risk_orders_safety.py` and `test_t5_operator_surface.py`; owner-led live UI/CLI drill on VM pending T6-03.)*
- [ ] The key is **Read plus Trade only**; the start check confirms `canWithdraw` and `canWithdrawFiat` false. *(Enforced in code and verified on mock in `test_s3_*` and `test_t4_risk_orders_safety.py`; live key check awaits owner key.)*
- [ ] The master key is in its decided custody and a re-entry procedure has been rehearsed (ADR-029). *(Procedure documented in `docs/10-OPERATIONS/06-RUNBOOKS.md` R10; owner rehearsal on VM pending T6-03.)*
- [ ] A restore of the `trading` schema has been rehearsed, with its time recorded (ADR-040). *(Rehearsal script prepared at `deploy/trader/rehearse_restore.sh` and documented in Runbook R14; owner execution on VM pending T6-03.)*
- [ ] The out-of-process liveness check alerts on a stopped Trader (ADR-039). *(Script `deploy/trader/check_liveness.py` and `Acceptance A13` verified against a fake Telegram server in `tests/trader/test_liveness_monitor.py`; host cron installation awaits owner approval per Runbook R14.)*
- [ ] The notification channel is chosen, tested, and carries no secret or balance (ADR-031). *(Redaction verified in `test_s14_*` and `test_t5_operator_surface.py`; live Telegram token entry on VM is owner-led.)*
- [ ] An independent review of the operator API, credential flow, and kill switch is recorded. *(Review packet prepared in `docs/09-SECURITY-PRIVACY/00-THREAT-MODEL.md`; owner chooses the reviewer.)*

**Process**
- [ ] The strategy has met the `PAPER` to `APPROVAL` gates with thresholds the owner set in advance (OQ-12). *(Threshold store, API, UI editor, and backtest gate evidence built in `MEMORY/records/2026-11-15-j4-missing-features.md`; owner sets OQ-12 numbers.)*
- [ ] Initial live capital is the owner's stated small amount (OQ-16). *(Owner-led.)*
- [ ] The owner has read the threat model's accepted residual risks and the runbooks. *(Owner-led.)*

## Before Considering `AUTO`

- [ ] At least four weeks in `APPROVAL` with real capital (ADR-020).
- [ ] Reconciliation runs clean across that period, with no unexplained difference.
- [ ] No unexplained kill-switch or breaker event; incident records reviewed.
- [ ] Live fill quality compared with paper assumptions, within the owner's tolerance.
- [ ] The owner has set and met the thresholds in advance, and records the decision to promote.
- [ ] A fresh threat-model review.

## After Each Release

- [ ] The running image digest equals the intended tag.
- [ ] Reconciliation is clean; health and clock skew are normal.
- [ ] The owner resumed trading explicitly.
- [ ] The release record is written and `TASKS/PROGRESS.md` updated.
