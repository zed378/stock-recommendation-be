"""background job queue: claiming, retries, dedup

Revision ID: 371022dfaa5b
Revises: 9bdcfc488a3b
Create Date: 2026-08-04 16:09:52.628507
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
import aidss.db.base
revision: str = '371022dfaa5b'
down_revision: str | None = '9bdcfc488a3b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Named explicitly. Autogenerate emitted `None`, which PostgreSQL would have
#: turned into a generated name on the way up and `drop_constraint(None, ...)`
#: would then have failed on the way down - a downgrade that cannot run is not
#: a downgrade.
DEDUP_CONSTRAINT = "uq_job_queue_dedup_key"


def upgrade() -> None:
    # `server_default` on the two NOT NULL columns is the adjustment
    # autogenerate asks for: adding a non-nullable column to a table that
    # already has rows fails without one, and this table is not guaranteed
    # empty in a deployment that has been running.
    op.add_column(
        "job_queue",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "job_queue",
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "job_queue",
        sa.Column(
            "available_at",
            aidss.db.base.UTCDateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "job_queue", sa.Column("locked_at", aidss.db.base.UTCDateTime(timezone=True), nullable=True)
    )
    op.add_column("job_queue", sa.Column("locked_by", sa.String(length=80), nullable=True))
    op.add_column("job_queue", sa.Column("dedup_key", sa.String(length=200), nullable=True))
    op.add_column(
        "job_queue", sa.Column("started_at", aidss.db.base.UTCDateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "job_queue",
        sa.Column("finished_at", aidss.db.base.UTCDateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_job_claimable", "job_queue", ["status", "available_at"], unique=False)
    op.create_index(
        op.f("ix_job_queue_available_at"), "job_queue", ["available_at"], unique=False
    )
    op.create_unique_constraint(DEDUP_CONSTRAINT, "job_queue", ["dedup_key"])


def downgrade() -> None:
    op.drop_constraint(DEDUP_CONSTRAINT, "job_queue", type_="unique")
    op.drop_index(op.f("ix_job_queue_available_at"), table_name="job_queue")
    op.drop_index("ix_job_claimable", table_name="job_queue")
    for column in (
        "finished_at",
        "started_at",
        "dedup_key",
        "locked_by",
        "locked_at",
        "available_at",
        "result",
        "max_retries",
    ):
        op.drop_column("job_queue", column)
