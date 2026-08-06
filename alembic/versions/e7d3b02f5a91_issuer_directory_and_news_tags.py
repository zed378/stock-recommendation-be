"""the listed-company directory, and which issuers a story is about

Revision ID: e7d3b02f5a91
Revises: d5b2914c7ae0
Create Date: 2026-08-06 09:12:44.310277
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e7d3b02f5a91'
down_revision: str | None = 'd5b2914c7ae0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: JSON on SQLite, JSONB on PostgreSQL - the same variant the models declare.
JSON_VARIANT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # --- the directory ---------------------------------------------------
    #
    # Deliberately not rows in `assets`. An asset is an instrument the platform
    # holds data for and can analyse; all 962 listed companies in there would
    # advertise 962 analysable instruments backed by prices for a handful. This
    # is reference data used to decide who a news story is about.
    op.create_table(
        "issuers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("sub_sector", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("listing_board", sa.String(length=60), nullable=True),
        sa.Column("listed_on", sa.Date(), nullable=True),
        sa.Column("website", sa.String(length=300), nullable=True),
        # Editable after import. Derivation cannot know that BBRI is "BRI", so
        # a correction has to survive the next scheduled sync.
        sa.Column("aliases", JSON_VARIANT, nullable=False),
        # Delisted issuers stay. Their news still refers to them, and a tag
        # pointing at a deleted row is worse than one pointing at a company
        # that no longer trades.
        sa.Column("is_listed", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_issuers_ticker"), "issuers", ["ticker"], unique=True)

    # --- who a story is about --------------------------------------------
    #
    # A table rather than a column on news_items, because one story is
    # regularly about several companies and `news_items.asset_id` holds one.
    # That column keeps its own meaning: which asset's scheduled fetch
    # retrieved the article, which is not the same fact as who it is about.
    op.create_table(
        "news_item_issuers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("news_item_id", sa.Uuid(), nullable=False),
        sa.Column("issuer_id", sa.Uuid(), nullable=False),
        # Denormalised: nearly every read wants the code, and a join for four
        # characters is a join on every news query.
        sa.Column("ticker", sa.String(length=20), nullable=False),
        # `native_enum=False`, and the *values* rather than the member names,
        # because that is what `enum_column` declares and what the code stores.
        # A native enum of "TICKER_CODE" would reject every "ticker_code" the
        # application writes - and being a CHECK constraint, it fails at insert
        # time rather than at migration time.
        sa.Column(
            "method",
            sa.Enum(
                "ticker_code",
                "company_name",
                "alias",
                name="tagmethod",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        # The text that matched, so a wrong tag names its own cause and the
        # alias behind it can be corrected.
        sa.Column("matched_text", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("news_item_id", "issuer_id", name="uq_news_item_issuer"),
    )
    op.create_index(
        op.f("ix_news_item_issuers_news_item_id"),
        "news_item_issuers",
        ["news_item_id"],
    )
    op.create_index(
        op.f("ix_news_item_issuers_issuer_id"), "news_item_issuers", ["issuer_id"]
    )
    # "the news for BBRI" is the query this table exists to serve, and it runs
    # on the code rather than on the id.
    op.create_index(op.f("ix_news_item_issuers_ticker"), "news_item_issuers", ["ticker"])


def downgrade() -> None:
    op.drop_index(op.f("ix_news_item_issuers_ticker"), table_name="news_item_issuers")
    op.drop_index(op.f("ix_news_item_issuers_issuer_id"), table_name="news_item_issuers")
    op.drop_index(
        op.f("ix_news_item_issuers_news_item_id"), table_name="news_item_issuers"
    )
    op.drop_table("news_item_issuers")
    op.drop_index(op.f("ix_issuers_ticker"), table_name="issuers")
    op.drop_table("issuers")
    # No enum type to drop: `native_enum=False` is a VARCHAR with a CHECK
    # constraint, which goes with the table.
