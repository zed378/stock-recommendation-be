"""phase 5: store enum values rather than member names

Revision ID: 9bdcfc488a3b
Revises: 34363225ea8e
Create Date: 2026-08-04 13:39:33.662016

Enum columns previously persisted the Python member *name* (``WATCHLIST``)
while the API, the JSON snapshots, and every StrEnum comparison in the code
used the *value* (``watchlist``). One fact written two ways in one database:
a dashboard filtering ``WHERE label = 'buy'`` silently returned nothing.

The columns are plain VARCHAR, so there is no DDL change - autogenerate
correctly found none. What does need changing is the data already in them,
which would otherwise fail to load once the mapping expects values.

For every enum in this schema the member name is exactly the upper-case form
of its value, so `lower()` is the complete mapping. It is also idempotent,
which makes this migration safe to re-run.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '9bdcfc488a3b'
down_revision: str | None = '34363225ea8e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column) for every enum-backed column in the schema.
ENUM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "role"),
    ("portfolio_holdings", "input_method"),
    ("ticker_news_schedules", "status"),
    ("recommendations", "label"),
    ("recommendations", "horizon"),
    ("audit_logs", "actor_type"),
    ("job_queue", "status"),
    ("provider_ingestion_runs", "status"),
)


def upgrade() -> None:
    for table, column in ENUM_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = lower({column}) WHERE {column} IS NOT NULL"  # noqa: S608
        )


def downgrade() -> None:
    for table, column in ENUM_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = upper({column}) WHERE {column} IS NOT NULL"  # noqa: S608
        )
