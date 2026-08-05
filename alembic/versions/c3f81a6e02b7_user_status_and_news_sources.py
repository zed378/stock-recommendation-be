"""account status, and the news sources the RSS provider reads

Revision ID: c3f81a6e02b7
Revises: a1c7e40b93d2
Create Date: 2026-08-05 16:40:22.118904
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c3f81a6e02b7'
down_revision: str | None = 'a1c7e40b93d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users: a status, not a boolean ---------------------------------
    #
    # `is_active` could say an account was off but not whether that was a
    # two-day suspension or a permanent ban, so the reason had to live
    # somewhere else - and a flag that can disagree with the reason beside it
    # is how a banned account ends up able to sign in. The column is dropped
    # rather than kept in step, because a mirror is the same bug with an extra
    # step.
    # The same type the model declares, down to the length and the constraint
    # name. A plain String here parses and stores identically, and `alembic
    # check` still calls it drift - which turns the one command that answers
    # "does the database match the code?" into noise nobody reads.
    op.add_column(
        'users',
        sa.Column(
            'status',
            sa.Enum(
                'active',
                'suspended',
                'banned',
                name='userstatus',
                native_enum=False,
                length=20,
            ),
            nullable=False,
            server_default='active',
        ),
    )
    op.add_column('users', sa.Column('suspended_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('status_reason', sa.Text(), nullable=True))
    op.add_column(
        'users', sa.Column('status_changed_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_users_status', 'users', ['status'])

    # Carried over before the old column goes. An account someone had already
    # switched off must not come back on as part of a schema change.
    op.execute("UPDATE users SET status = 'suspended' WHERE is_active = false")
    op.drop_column('users', 'is_active')

    # --- news_sources: the feeds that were never there -------------------
    op.create_table(
        'news_sources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('feed_url', sa.String(length=1000), nullable=False),
        sa.Column('asset_id', sa.Uuid(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(length=20), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_entry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feed_url'),
    )
    op.create_index('ix_news_sources_asset_id', 'news_sources', ['asset_id'])


def downgrade() -> None:
    op.drop_index('ix_news_sources_asset_id', table_name='news_sources')
    op.drop_table('news_sources')

    op.add_column(
        'users',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # Both suspended and banned were "off" under the old boolean.
    op.execute("UPDATE users SET is_active = false WHERE status <> 'active'")
    op.drop_index('ix_users_status', table_name='users')
    op.drop_column('users', 'status_changed_at')
    op.drop_column('users', 'status_reason')
    op.drop_column('users', 'suspended_until')
    op.drop_column('users', 'status')
