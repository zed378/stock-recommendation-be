"""Let a saved screen run on its own cron.

The schedule lives on the screen rather than in `scheduler_jobs`, for the same
reason `ticker_news_schedules` does: it belongs to one user's one screen, and a
generic job table has nowhere to put that.

`last_match_count` is stored even when it is zero. A scheduled screen that
never notifies is otherwise indistinguishable from one that stopped running,
and the row is where that question gets answered without interrupting anybody
to say nothing happened.

Revision ID: d3f6b81c204a
Revises: c7e2a934b158
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d3f6b81c204a"
down_revision: str | None = "c7e2a934b158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_screens",
        sa.Column("cron_expr", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "saved_screens", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "saved_screens", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("saved_screens", sa.Column("last_match_count", sa.Integer(), nullable=True))
    op.add_column("saved_screens", sa.Column("last_error", sa.String(length=400), nullable=True))
    # The scheduler asks "which are due" on every tick, and that is the only
    # query this column exists for.
    op.create_index("ix_saved_screens_next_run_at", "saved_screens", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_saved_screens_next_run_at", table_name="saved_screens")
    for column in ("last_error", "last_match_count", "last_run_at", "next_run_at", "cron_expr"):
        op.drop_column("saved_screens", column)
