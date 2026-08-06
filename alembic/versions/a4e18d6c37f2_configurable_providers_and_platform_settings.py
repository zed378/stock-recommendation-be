"""providers carry their own credentials; operator settings leave the environment

Revision ID: a4e18d6c37f2
Revises: f2a91c47b608
Create Date: 2026-08-06 14:22:09.663104
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a4e18d6c37f2'
down_revision: str | None = 'f2a91c47b608'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # --- providers reach their own endpoint ------------------------------
    #
    # Every row used to be built from the environment, so all of them shared
    # one base URL and one key. Several rows could then differ only by model
    # name against a single endpoint - which is not multi-provider, it is one
    # provider listed several times, and the fallback chain had nowhere else to
    # fail over to.
    #
    # The credential is encrypted at rest and never returned by the API. That
    # is weaker than a secret manager - the application can decrypt it, so a
    # database dump plus the application secret recovers every key - and it is
    # the price of being able to add a provider without a redeploy.
    op.add_column("ai_providers", sa.Column("api_key_ciphertext", sa.Text(), nullable=True))
    op.add_column("ai_providers", sa.Column("api_key_hint", sa.String(length=40), nullable=True))
    # Per provider because they differ by an order of magnitude: a hosted API
    # answers in seconds, a self-hosted model on modest hardware needs minutes
    # for the same prompt.
    op.add_column("ai_providers", sa.Column("timeout_seconds", sa.Float(), nullable=True))
    # Inference an operator controls but publishes at a public domain is
    # indistinguishable from a third-party API by inspection, and the
    # difference decides whether personal financial data may be sent there.
    op.add_column(
        "ai_providers",
        sa.Column("self_hosted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ai_providers", sa.Column("last_status", sa.String(length=20), nullable=True))
    op.add_column("ai_providers", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column(
        "ai_providers", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- operator decisions that must not need a redeploy -----------------
    #
    # `AIDSS_*` is set by whoever deploys, applies at boot, and needs a restart
    # to change. Correct for a database URL, wrong for "is registration open
    # right now" - a decision someone makes at 11pm because a link leaked.
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        # Values are wrapped as {"value": ...}: a JSON column holding `false`
        # and one holding SQL NULL are hard to tell apart through an ORM, and
        # "registration is closed" must never read as "nobody has set this".
        sa.Column("value", JSON_VARIANT, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    for column in (
        "last_checked_at",
        "last_error",
        "last_status",
        "self_hosted",
        "timeout_seconds",
        "api_key_hint",
        "api_key_ciphertext",
    ):
        op.drop_column("ai_providers", column)
