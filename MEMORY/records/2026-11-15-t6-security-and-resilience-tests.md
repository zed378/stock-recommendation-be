# T6-01 and T6-02: security and resilience tests (mock only), and what they found

**Date:** 2026-11-15
**Task:** T6-01 (tests part), T6-02
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/11-TESTING-QUALITY/05`, `06`; `docs/09-SECURITY-PRIVACY/00`

---

## Hook

S1 to S17 and R1 to R11 exist as named tests, plus P1 to P4, P6, and a PAPER soak. Writing them found **seven real
defects, all fixed**, and four requirements that are **not met** and are recorded instead of passed. Everything ran
against the synthetic mock and SQLite; none of it touches a real exchange.

---

## Defects Found And Fixed

| # | Found by | Defect | Fix |
|---|---|---|---|
| 1 | S8 | The Trader API sent no security headers | `nosniff`, frame denial, `no-store`, a locked-down CSP and `no-referrer` on every response |
| 2 | S7 | `Idempotency-Key` was required but never honoured, so a double click ran twice | A replay cache keyed by caller, method, path, and key; a reused key with a different body is a 409. **In memory, so lost on restart** (the approval and kill paths are idempotent by their own design) |
| 3 | R1 | The exit monitor needed the private account call to succeed, so with the account endpoint down and the ticker up no stop was evaluated | Prices are fetched first and on their own; a held position is still priced if one allowlist entry is bad; a stop can be sent from a minimal snapshot |
| 4 | R1 | A reconciliation that could not read the exchange left a difference nobody could resolve, so the Trader could never be resumed after an outage | A later clean run supersedes `reconcile_failed` differences; real data differences still need the owner |
| 5 | R11 | A log handler that raises (a full disk) inside the loop's `except` block would skip the protective steps after it | `safe_log` everywhere the trading path logs |
| 6 | R10 | The lease update compared naive and aware datetimes in Python when the row was already loaded | The comparison is left to the database (`synchronize_session=False`) |
| 7 | R3 | During a price outage the snapshot asked for the same prices a second time | The snapshot is skipped when the prices already failed |

## Requirements Not Met (recorded, not passed)

- **S13, floating dependencies:** every dependency is a lower bound and there is no lock file. The test is a strict
  `xfail`, so pinning flips it.
- **S15, a user cannot change their own role:** the analysis platform lets an admin change their own role on purpose
  (`allow_self=True`; stepping down is real, the last admin is protected). It cannot escalate anyone, but the spec
  sentence is not true as written.
- **R5, a frozen price feed:** freshness is the age of the last *successful* call. A feed that keeps answering with
  the same stale value is not detected. Calls that fail are.
- **S6, every order path preceded by a risk result:** the kill switch's `FLATTEN` sends MARKET sells without one, by
  design (it is the emergency path). The test asserts the manager path and that only the manager and kill switch can
  mutate orders.
- R1 asks for a "connector breaker". There is no such object; the same outage ends in the stale-data breaker or a
  failed reconciliation, both of which halt.

## Not Done, Not Verified

- **The independent review (T6-01) is not done**; the owner chooses the reviewer.
- S11's `UPDATE` and `DELETE` denial as `trader_rw` is PostgreSQL behaviour, proven by `test_privileges_postgres.py`
  (passed once on the VM on 2026-11-15), not by the S11 test here, which proves the hash chain.
- S13's image scan, S17's image-layer scan, and the repository being private before T5-06 are CI and owner steps. The
  S17 test only scans tracked files for key-shaped strings.
- **P5** (dashboard query plans) is not done. P1 to P4 and P6 are asserted against the structural limits (half the
  documented Indodax limits, 2P+2 requests per reconciliation, one polling interval for a stop), not against a target
  the owner chose, because none is set.
- The soak is 400 cycles of simulated time (about 73 minutes), not a real-time run. Memory is Python's own
  (`tracemalloc`), not the container's.
- Failure injection used the mock's responses; a real exchange can fail in ways the mock does not.
