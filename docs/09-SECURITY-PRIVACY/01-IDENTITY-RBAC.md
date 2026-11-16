# 01 — Identity and RBAC

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | Security Engineer |
| **Decided by** | ADR-015 |
| **Open items** | OQ-14 (resolved, ADR-028), OQ-21 (resolved, ADR-033) |

## Identity

The Trader reuses the platform's login and JWT (bcrypt-hashed passwords, JWT bearer tokens, per-user
ownership checks in the query layer), so the owner has one identity. The Trader validates a token by calling the analysis API's `GET /auth/me` (ADR-028) and does **not** hold the
platform's `AIDSS_JWT_SECRET`, because holding the signing secret would let a compromised Trader mint tokens
for the analysis platform. `/auth/me` re-checks user status on each request, so a suspended user's token stops
working at once. **To verify before building:** that the response carries the role needed, and that a `trader`
role can be added to the platform's `UserRole` (a change in `aidss` that must keep its architecture test
passing).

## Roles

Existing: `viewer`, `investor`, `admin`. New: `trader` (ADR-015). The matrix is in
`../01-PRODUCT-REQUIREMENTS/06-ROLE-PERMISSION-MATRIX.md`.

## Enforcement

| Rule | Detail |
|---|---|
| Server-side | Every route declares a permission; the Trader checks it. A UI element hidden by role is a convenience |
| Role changes | Audited; a user cannot change their own role |
| No automated actor | A job, strategy, or integration cannot hold `trade:approve`, `trade:promote`, or `trade:configure_risk` |
| One owner | There is no two-person rule (ADR-015); the audit log and gates compensate |
| Suspended users | A suspended account loses access immediately. The platform already checks status on each request so that a token issued before a suspension does not stay valid for its hour |

## Step-Up for High-Impact Actions (ADR-046, accepted (owner, 2026-11-16))

For `FLATTEN`, promotion to `AUTO`, raising a limit, and credential changes, require a **recent
authentication** (single-use 5-minute password re-entry grant) in addition to a valid token,
so a stolen idle session cannot do the most damaging things. Recorded in `MEMORY/DECISIONS.md` ADR-046.

## Sessions

Short-lived access tokens as the platform already issues. The operator surface shows the signed-in user and
the time of the last sensitive action.

## Service-to-Service

The Trader's access to the analysis platform uses a credential scoped to read-only context (ADR-032). It is a
separate credential from any user's, rotatable, and held encrypted.

## Tests (planned)

Each permission has an allowed and a denied case; every route is covered by the enumeration test; a
suspended token is rejected; a self role change is refused; no non-human actor can approve.
