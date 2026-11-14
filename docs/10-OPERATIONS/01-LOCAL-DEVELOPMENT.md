# 01 — Local Development

| | |
|---|---|
| **Status** | Draft, 2026-11-14 |
| **Owner** | DevOps Engineer |
| **Decided by** | ADR-001 |

**The Trader's local setup does not exist yet.** This describes the intended workflow so T1-01 builds toward
it. For the analysis platform, the verified commands are in `../../CLAUDE.md` and `../../README.md`.

## Prerequisites

Python 3.11 or newer, Docker (for PostgreSQL), the repository's `.venv`.

## Intended Flow

```
# 1. Environment (the analysis platform's existing steps)
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"        # Linux/macOS: .venv/bin/python

# 2. Database
docker compose up -d postgres

# 3. Trader schema, roles, and migrations         (commands defined by T1-01 / T1-03)
# 4. Mock exchange server                           (defined by T2-01)
# 5. Run the Trader against the mock exchange       (defined by T1-01)
```

Nothing in this flow talks to the real Indodax. A developer never needs a real key.

## What a Developer Needs

| Need | Provided by |
|---|---|
| An exchange to talk to | The mock exchange (`11/07`), which verifies the signature scheme with **test-only** keys defined in the tests |
| Realistic data | Fixtures shaped from the documentation and labelled synthetic |
| A scheduler clock | An injectable clock, so candle-close and time-based behavior can be tested deterministically |
| A database | Local PostgreSQL; a SQLite path for the hermetic suite where the behavior is dialect-neutral. Column-level privileges and the roles need PostgreSQL, so those tests are marked `postgres` |

## Rules for Local Work

- **Never put a real key in a local file**, including `.env`. The repository's `.env` is git-ignored but
  still not a place for it.
- **Do not point the Trader at production Indodax from a development machine** except for the owner-led
  read-only verification (T2-07), and then with a Read-only key.
- Use the same lint and type settings as the rest of the repository (`ruff`).
- Commit with the task ID in the subject (`TASKS/00-TASK-CONVENTIONS.md`).

## Running Tests

The hermetic suite (mock exchange, SQLite where valid) runs by default. PostgreSQL-dependent tests are
opt-in with a marker, as the analysis platform does with `-m postgres`. A `live_readonly` marker, always
deselected, is reserved for the owner-led check and refuses to run without an explicit environment
confirmation.

## Troubleshooting Signing Problems

A failing signature against the mock exchange is usually an encoding or ordering mismatch between what is
signed and what is sent (`06-INTEGRATIONS/04`). The mock reports which part differed, in test mode only.
