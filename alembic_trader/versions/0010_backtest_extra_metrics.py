"""Extra backtest metrics (ADR-063). Additive and nullable.

Revision ID: 0010_backtest_extra_metrics
Revises: 0009_intent_strategy_id
Create Date: 2026-11-19

Raw sums for expectancy, average win and loss, holding time and fees. NULL on a run stored before
this migration. Added only if missing, because a database built from the current models by the
earlier migrations already has it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from aidss_trader.db.base import SCHEMA

revision = "0010_backtest_extra_metrics"
down_revision = "0009_intent_strategy_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    schema = SCHEMA if bind.dialect.name == "postgresql" else None
    columns = {c["name"] for c in sa.inspect(bind).get_columns("backtest_run", schema=schema)}
    if "extra_metrics" not in columns:
        op.add_column(
            "backtest_run", sa.Column("extra_metrics", sa.JSON(), nullable=True), schema=schema
        )


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07); production never drops a column.
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    op.drop_column("backtest_run", "extra_metrics", schema=schema)
