"""Issuer calendar, sharing between accounts, and an owner on each analysis.

Three changes that arrived together.

`issuer_agenda` is the first table here that states something about the future.
It is keyed on ticker rather than asset_id like the market scan, because the
calendar covers the whole exchange and most issuers on it have no Asset row.

`shared_items` records a grant rather than a copy, and names its recipient
rather than minting a link - see the model docstring for why a shareable URL
was rejected.

`analysis_results.conversation_id` closes a gap that predates both: the engine
always knew which conversation a run belonged to and stored only the analysis,
so "who asked for this" was answerable while the call was on the stack and not
afterwards. Sharing needs it afterwards, and so does the traceability the
platform claims.

Revision ID: b4d1f8a2c907
Revises: a1c8e4f70d23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b4d1f8a2c907"
down_revision: str | None = "a1c8e4f70d23"
branch_labels = None
depends_on = None

# Non-native enums with lowercase values, matching `enum_column`. A migration
# that declares `sa.Enum("EARNINGS", ...)` builds a native type whose labels are
# the Python member names, and every insert then fails on the value - which
# reads as a data bug rather than a schema one.
_AGENDA_KIND = sa.Enum(
    "earnings", "rups", "dividend", "ex_date", "stock_split", "rights_issue", "other",
    name="agendakind",
    native_enum=False,
)
_AGENDA_SOURCE = sa.Enum(
    "exchange", "news", "manual", name="agendasource", native_enum=False
)
_SHARE_KIND = sa.Enum("watchlist", "analysis", name="sharekind", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "issuer_agenda",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("kind", _AGENDA_KIND, nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=400), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("source", _AGENDA_SOURCE, nullable=False),
        sa.Column("source_url", sa.String(length=600), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ticker", "kind", "scheduled_for", name="uq_agenda_event"),
    )
    op.create_index("ix_issuer_agenda_ticker", "issuer_agenda", ["ticker"])
    op.create_index("ix_issuer_agenda_scheduled_for", "issuer_agenda", ["scheduled_for"])
    op.create_index("ix_agenda_upcoming", "issuer_agenda", ["scheduled_for", "ticker"])

    op.create_table(
        "shared_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _SHARE_KIND, nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "owner_id", "recipient_id", "kind", "subject_id", name="uq_share_target"
        ),
    )
    op.create_index("ix_shared_items_owner_id", "shared_items", ["owner_id"])
    op.create_index("ix_shared_items_recipient_id", "shared_items", ["recipient_id"])
    op.create_index("ix_share_recipient", "shared_items", ["recipient_id", "revoked_at"])

    op.add_column(
        "analysis_results",
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_analysis_results_conversation_id", "analysis_results", ["conversation_id"]
    )
    op.create_foreign_key(
        "fk_analysis_conversation",
        "analysis_results",
        "ai_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_analysis_conversation", "analysis_results", type_="foreignkey")
    op.drop_index("ix_analysis_results_conversation_id", table_name="analysis_results")
    op.drop_column("analysis_results", "conversation_id")
    op.drop_table("shared_items")
    op.drop_table("issuer_agenda")
