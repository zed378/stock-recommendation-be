# Phase T1 — Foundation

| | |
|---|---|
| **Status** | ⏳ TODO |
| **Depends on** | T0 accepted by the owner |
| **Exit criteria** | The Trader service exists, builds into a private image, runs with no exchange access, has its own schema and roles with privileges verified, guard tests in CI, an encrypted credential store with a dedicated master key, an append-only audit log, and a single-instance lease. The analysis platform's architecture test passes **unmodified** |

**Decided:** OQ-14 (ADR-028), OQ-17 (ADR-029), OQ-24 (ADR-030). Nothing blocks T1 except the owner accepting T0.

---

### T1-01 — Scaffold `aidss_trader`, `Dockerfile.trader`, Compose service

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T0 accepted |
| **Spec refs** | `docs/02-ARCHITECTURE/02-C4-CONTAINERS.md` · `docs/10-OPERATIONS/02-DEPLOYMENT-ARCHITECTURE.md` · `docs/09-SECURITY-PRIVACY/07-SOFTWARE-SUPPLY-CHAIN.md` |
| **Spec required** | yes |
| **Open numbers** | none |
| **Owner-led** | no |

**Why:** Everything else builds on a separate package, image, and service (ADR-001, ADR-021).

**Definition of Done**
- [ ] Package `src/aidss_trader/` with the layout in `02-ARCHITECTURE/03`; no import of `aidss`
- [ ] `Dockerfile.trader`: non-root, no torch, no test suite, no secrets; builds locally
- [ ] Compose service defined with `image:` only, no `build:`
- [ ] Health check covers process, lease, and a recent cycle
- [ ] The commands for the Trader are added to `CLAUDE.md` § Commands, verified by running them
- [ ] Operator-surface token verification via the analysis API's `GET /auth/me` is checked and the `trader` role plan recorded (ADR-028)

**Abuse cases**
- Putting trading code under `src/aidss` "for now". The guard (T1-02) must fail it.
- Putting a secret, a configuration value, or an owner number in the image (it is public during development, ADR-030).
- Forgetting to make the repository private before T5-06.

### T1-02 — Guard tests

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-01 |
| **Spec refs** | `docs/11-TESTING-QUALITY/00-TEST-STRATEGY.md` · `docs/02-ARCHITECTURE/03-COMPONENT-ARCHITECTURE.md` |
| **Spec required** | no |

**Definition of Done**
- [ ] Import-boundary test: `aidss` does not import `aidss_trader`; the reverse is limited to the documented
      interface
- [ ] `tests/test_architecture_constraints.py` passes unmodified (a CI check that its content is unchanged)
- [ ] Scaffolds for the no-withdrawal allowlist, no-float, no-order-route, and dependency-rule tests
- [ ] Each guard has a deliberately failing example proving it can fail

**Abuse cases**
- A guard that scans an empty tree and always passes. Each includes a "tree is not empty" check, as the
  existing test does.

### T1-03 — Schema `trading`, roles, privileges, Alembic environment

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-01 |
| **Spec refs** | `docs/03-DATA-MODEL/00` to `07` |
| **Spec required** | yes |

**Definition of Done**
- [ ] Schema `trading`; roles `trader_owner`, `trader_rw`; separate Alembic environment with its version
      table inside `trading`
- [ ] Tables for the foundation set; `NUMERIC(38,18)` for money; no float column
- [ ] Column-level `UPDATE` on `order`; `INSERT`/`SELECT` only on append-only tables
- [ ] Test (`postgres`): `trader_rw` cannot `UPDATE` or `DELETE` append-only tables; cannot write outside
      `trading`; the analysis role cannot write `trading`
- [ ] Drift test: empty database from migrations equals the models
- [ ] Additive migrations only

**Abuse cases**
- Granting `trader_rw` broad rights "to make tests pass".
- Resetting the database to fix a migration.

### T1-04 — Credential store with a dedicated master key

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-03 |
| **Spec refs** | `docs/05-MODULE-SPECIFICATIONS/13-CREDENTIAL-ADMINISTRATION.md` · `docs/09-SECURITY-PRIVACY/02-SECRETS-AND-KEY-ROTATION.md` |
| **Spec required** | yes |
| **Open numbers** | none (custody decided, ADR-029) |

**Definition of Done**
- [ ] Fernet with the master key read from the file named by `AIDSS_TRADER_MASTER_KEY_FILE` (ADR-029), **not** derived from `AIDSS_JWT_SECRET`
- [ ] Write-only API; masked hint; never logged or returned
- [ ] Atomic rotation; unreadable ciphertext leaves the Trader `DISABLED`
- [ ] Tests S1, S4, S5

**Abuse cases**
- Reusing `aidss.security.secrets` because it is convenient.
- A real key in a test or fixture.

### T1-05 — Audit log

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-03 |
| **Spec refs** | `docs/09-SECURITY-PRIVACY/04-AUDIT-LOGGING.md` · `docs/03-DATA-MODEL/05-RISK-AND-AUDIT-SCHEMA.md` |
| **Spec required** | yes |

**Definition of Done**
- [ ] Append-only `audit_log` with actor, action, before and after (redacted), mode, correlation id
- [ ] Hash-chain design decided and recorded as an ADR; verification job
- [ ] Test S11; every mutation path writes a row

### T1-06 — Configuration loading; "unset means disabled"

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-03 |
| **Spec refs** | `docs/10-OPERATIONS/00-ENVIRONMENTS-AND-CONFIG.md` · `docs/03-DATA-MODEL/08-SETTINGS-REGISTRY.md` · FR-T11 |
| **Spec required** | no |
| **Open numbers** | none (it must not default any) |

**Definition of Done**
- [ ] Infrastructure settings from the environment; operational settings from the database
- [ ] A required limit that is null disables the strategy and reports which
- [ ] A test that no limit has a default

**Abuse cases**
- Adding a "sensible default" for a limit.

### T1-07 — Lease and single-instance control

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-03 |
| **Spec refs** | ADR-027 · `docs/02-ARCHITECTURE/07-RESILIENCE-AND-DEGRADATION.md` |
| **Spec required** | no |
| **Open numbers** | none (TTL 15 s, heartbeat 5 s, ADR-043) |

**Definition of Done**
- [ ] Database lease with heartbeat; self-healing on expiry
- [ ] Integration I5: two processes, one trades
- [ ] The lease timeout is read from configuration

### T1-08 — Token verification and the `trader` role (touches the analysis platform)

| | |
|---|---|
| **Status** | TODO |
| **Depends on** | T1-01 |
| **Spec refs** | ADR-028 · `docs/09-SECURITY-PRIVACY/01-IDENTITY-RBAC.md` · `docs/01-PRODUCT-REQUIREMENTS/06-ROLE-PERMISSION-MATRIX.md` |
| **Spec required** | yes |
| **Open numbers** | none (ADR-033) |

**Why:** The Trader verifies logins by calling the analysis API's `GET /auth/me` and must know the user's role
(ADR-028). That needs a `trader` role the platform recognizes.

**Definition of Done**
- [ ] Verified: `GET /auth/me` returns the role and status the Trader needs, and re-checks status per request
- [ ] A `trader` value added to the platform's `UserRole`, with a migration if the stored enum needs one
- [ ] The platform's RBAC gives `trader` **no** analysis-platform privilege beyond what `viewer` has; the
      `trade:*` permissions live **only** in the Trader
- [ ] `tests/test_architecture_constraints.py` passes **unmodified**
- [ ] The Trader's verification client: short timeout, fails closed (the operator surface refuses), and the
      command-line kill tool does not depend on it
- [ ] The cache decision (none or a short TTL) is recorded

**Abuse cases**
- Adding order-related permissions or vocabulary to `aidss.security.rbac`.
- Giving the Trader the JWT signing secret "to simplify".
