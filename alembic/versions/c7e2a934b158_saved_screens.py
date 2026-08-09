"""Filters an investor writes for themselves.

Stored as the validated rule structure rather than as a rendered query, so a
screen naming a signal that later disappears can say which field went away
instead of failing with a database error.

Revision ID: c7e2a934b158
Revises: b4d1f8a2c907
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a934b158"
down_revision: str | None = "b4d1f8a2c907"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_screens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "rules",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_screen_name"),
    )
    op.create_index("ix_saved_screens_user_id", "saved_screens", ["user_id"])


def downgrade() -> None:
    op.drop_table("saved_screens")
