# T1 — Foundation (built, in review)

**Date:** 2026-11-14
**Task:** T1-01 to T1-08 (`TASKS/PHASE-T1-FOUNDATION.md`)
**Author:** Claude (AI agent), working with the project owner
**Spec refs:** `docs/02-ARCHITECTURE/02`, `03`; `docs/03-DATA-MODEL/05`, `07`, `08`; `docs/05-MODULE-SPECIFICATIONS/13`; `docs/09-SECURITY-PRIVACY/02`, `04`; ADR-001, 014, 021, 027, 028, 029, 030, 043

---

## Hook

The safety scaffolding exists and its logic is tested, but the three things that would prove it works in
production were **not** verified: PostgreSQL privileges, the Docker image, and the Compose override. No
PostgreSQL or Docker was available.

---

## What Changed

| Item | Detail |
|---|---|
| New package | `src/aidss_trader/`: `config`, `db`, `credentials`, `audit`, `lease`, `service`, CLI |
| Credential store | Fernet with a master key read from a **file** (`AIDSS_TRADER_MASTER_KEY_FILE`), not derived from `AIDSS_JWT_SECRET` (ADR-014, ADR-029) |
| Audit log | Append-only, hash-chained; detects an altered or removed row |
| Lease | Single instance; TTL 15 s, heartbeat 5 s (ADR-043) |
| Limits | `RiskLimits`: no loss-limiting field has a default; unset means disabled (FR-T11) |
| Migrations | Separate Alembic environment (`alembic_trader/`), version table in schema `trading`; grants in the migration |
| Deploy files | `Dockerfile.trader`, `deploy/trader/docker-compose.trader.yml`, `deploy/trader/bootstrap.sql` |
| Analysis platform | `UserRole.TRADER` and an RBAC entry equal to `viewer` (T1-08). Nothing else in `src/aidss` changed |
| Tests | `tests/trader/` (40: 37 run by default, 3 opt-in PostgreSQL) |

---

## Why

Phase T1 of the plan, built before any exchange contact (phase rule). Choices already decided: ADR-001
(separate package), ADR-014/029 (key file), ADR-021 (schema and roles), ADR-027/043 (lease), ADR-028 (`trader` role).

---

## Alternatives Considered

A single distribution with the analysis platform (chosen: one `pyproject`, the Trader image copies only
`src/aidss_trader`); a PostgreSQL advisory lock for the lease (rejected, ADR-027).

---

## What Surprised Me

1. **The analysis API connects as the database's bootstrap superuser**, which bypasses every grant. ADR-021's role
   isolation is therefore not real until that API uses a limited role. Recorded in `TASKS/BACKLOG.md` and in
   `bootstrap.sql`; it needs the owner (a deployment change outside the Trader).
2. **SQLite returns naive datetimes**, so `astimezone` read them as local time and would have changed the audit
   hash. Normalized to UTC; a test would have caught it only because the chain is re-read after a commit.
3. **The audit timestamp cannot come from the database** if the row is hashed before insert and never updated.
   `docs/09/04` now says so.

---

## Tests

Run on 2026-11-14:

- `ruff check src tests alembic_trader`: clean.
- `pytest` (full): **1,797 passed, 1 failed, 31 deselected.** The failure is
  `tests/test_output_language.py::test_translation_covers_every_prose_field`, pre-existing and unrelated.
- `tests/test_architecture_constraints.py` passed, **file unmodified**.
- Trader tests by name:
  - credentials: `test_roundtrip_and_ciphertext_is_not_plaintext`, `test_a_changed_master_key_makes_the_credential_unreadable`,
    `test_the_master_key_is_not_derived_from_the_jwt_secret`, `test_rotation_leaves_exactly_one_active_credential`,
    `test_generate_master_key_refuses_to_overwrite`
  - audit: `test_an_untouched_chain_verifies`, `test_altering_a_row_is_detected`, `test_removing_a_row_is_detected`,
    `test_sentinel_secrets_are_redacted_before_they_are_stored`
  - lease: `test_another_instance_takes_over_only_after_expiry`, `test_a_non_holder_cannot_release`
  - config/service: `test_no_loss_limiting_setting_has_a_default`, `test_t1_trader_is_always_disabled_and_says_why`
  - guards: `test_aidss_never_imports_the_trader`, `test_the_trader_never_imports_aidss`,
    `test_no_withdrawal_or_fund_movement_code_exists`, `test_the_withdrawal_guard_can_fail`,
    `test_every_table_is_in_the_trading_schema_and_no_money_column_is_a_float`
  - migration: `test_upgrade_creates_exactly_the_foundation_tables`
  - role: `test_trader_role_exists_and_equals_a_viewer`, `test_no_trading_permission_is_defined_in_the_analysis_platform`
- **Not run:** `tests/trader/test_privileges_postgres.py` (3 tests). They assert that `trader_rw` cannot UPDATE or
  DELETE the audit log or a risk-limit version and cannot write outside `trading`.
- **Not built or run:** the Docker image; the Compose override; the migration against PostgreSQL.

---

## Definition of Done

- [x] Code implements the spec for the tested logic
- [x] Lint clean; full suite run; analysis architecture test passes unmodified
- [x] No path skips the Risk Engine (none exists yet); no withdrawal code; money is `Decimal`
- [ ] **PostgreSQL privileges verified**
- [ ] **Image built and the container started**
- [ ] Audit head hash recorded outside the database
- [ ] Operational settings loaded from the database
- [ ] Trader-side `GET /auth/me` verification client (T1-08)
- [ ] The owner has reviewed

**Waived:** none. Tasks stay `REVIEW`, not `DONE`.

---

## Security and Compliance

No credential was handled. Test keys are generated inside the tests. The master key file is created with mode
`0600` where the OS honours it (not meaningful on Windows). The deny-pattern redaction for audit payloads is
**interim** (docs prefer an allowlist).

---

## What to Watch

- The `trader_rw` privilege boundary is only as real as its first PostgreSQL run.
- The lease on PostgreSQL: the conditional UPDATE is portable but its race behaviour was only tested on SQLite.
- `Dockerfile.trader` installs the whole `pyproject` dependency list (no torch) but copies only `aidss_trader`; confirm
  the build resolves with that layout.

---

## What Was Not Determined

Whether the image builds; whether the migration and grants run on PostgreSQL; whether `GET /auth/me` carries
the role the Trader needs.

---

## Follow-Ups

`TASKS/BACKLOG.md` (superuser finding). Next: run the PostgreSQL tests and build the image (needs Docker), then T2.

---

## Links

- ADR: none new
- Previous record: `2026-11-14-owner-answers-batch-7.md`
