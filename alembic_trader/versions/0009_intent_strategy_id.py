"""Which strategy an intent came from (S2, ADR-062). Additive and nullable.

Revision ID: 0009_intent_strategy_id
Revises: 0008_indexes_idempotency
Create Date: 2026-11-19

NULL means the reference strategy `ema_adx`; nothing is rewritten. On a database built by the
earlier migrations from the current models the column is already there, so it is added only if
missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from aidss_trader.db.base import SCHEMA

revision = "0009_intent_strategy_id"
down_revision = "0008_indexes_idempotency"
branch_labels = None
depends_on = None

_INDEX = "ix_order_intent_strategy_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    schema = SCHEMA if bind.dialect.name == "postgresql" else None
    columns = {c["name"] for c in inspector.get_columns("order_intent", schema=schema)}
    if "strategy_id" not in columns:
        op.add_column(
            "order_intent",
            sa.Column("strategy_id", sa.String(48), nullable=True),
            schema=schema,
        )
    indexes = {i["name"] for i in inspector.get_indexes("order_intent", schema=schema)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, "order_intent", ["strategy_id"], schema=schema)


def downgrade() -> None:
    # Development databases only (docs/03-DATA-MODEL/07); production never drops a column.
    schema = SCHEMA if op.get_bind().dialect.name == "postgresql" else None
    op.drop_index(_INDEX, table_name="order_intent", schema=schema)
    op.drop_column("order_intent", "strategy_id", schema=schema)
