"""notification event vocabulary and structured context

Revision ID: a1c7e40b93d2
Revises: df94aedf2f33
Create Date: 2026-08-05 14:02:11.004312
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a1c7e40b93d2'
down_revision: str | None = 'df94aedf2f33'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both nullable, deliberately. The table may already hold rows, and there
    # is no honest default for either: an older notification was written before
    # the event vocabulary existed, so claiming it was any particular event
    # would be inventing a fact. Null reads as "unknown", which is true, and the
    # interface renders those by their subject line as it always did.
    op.add_column(
        'notifications',
        sa.Column('event', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'notifications',
        sa.Column(
            'context',
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
            nullable=True,
        ),
    )
    # The badge counts unread rows per user on every poll, and the list reads
    # the same rows ordered by recency. Without this it is a sequential scan of
    # every notification ever written, growing forever, several times a minute.
    op.create_index(
        'ix_notifications_user_status_created',
        'notifications',
        ['user_id', 'status', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_notifications_user_status_created', table_name='notifications')
    op.drop_column('notifications', 'context')
    op.drop_column('notifications', 'event')
