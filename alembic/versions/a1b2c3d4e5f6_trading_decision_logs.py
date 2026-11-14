"""trading_decision_logs: multi-agent debate and reflection memory

Revision ID: a1b2c3d4e5f6
Revises: d3f6b81c204a
Create Date: 2026-11-14 17:31:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import aidss.db.base

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "d3f6b81c204a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trading_decision_logs",
        sa.Column("id", aidss.db.base.GUID(), nullable=False),
        sa.Column("user_id", aidss.db.base.GUID(), nullable=True),
        sa.Column("asset_id", aidss.db.base.GUID(), nullable=False),
        sa.Column("analysis_result_id", aidss.db.base.GUID(), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=24), nullable=False),
        sa.Column("trade_date", aidss.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.Column(
            "final_rating",
            sa.Enum(
                "strong_buy",
                "buy",
                "watchlist",
                "hold",
                "reduce",
                "sell",
                name="recommendationlabel",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("investment_plan", sa.Text(), nullable=False),
        sa.Column("trader_proposal", sa.Text(), nullable=False),
        sa.Column("portfolio_decision", sa.Text(), nullable=False),
        sa.Column(
            "debate_trace",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("settled_at", aidss.db.base.UTCDateTime(timezone=True), nullable=True),
        sa.Column("settled_price", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("realized_return_pct", sa.Float(), nullable=True),
        sa.Column("outcome_label", sa.String(length=24), nullable=True),
        sa.Column("reflection_lesson", sa.Text(), nullable=True),
        sa.Column("created_at", aidss.db.base.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["analysis_results.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_decision_asset_date", "trading_decision_logs", ["asset_id", "trade_date"])
    op.create_index("ix_trading_decision_ticker_settled", "trading_decision_logs", ["ticker", "settled_at"])
    op.create_index(op.f("ix_trading_decision_logs_analysis_result_id"), "trading_decision_logs", ["analysis_result_id"])
    op.create_index(op.f("ix_trading_decision_logs_asset_id"), "trading_decision_logs", ["asset_id"])
    op.create_index(op.f("ix_trading_decision_logs_ticker"), "trading_decision_logs", ["ticker"])
    op.create_index(op.f("ix_trading_decision_logs_trade_date"), "trading_decision_logs", ["trade_date"])
    op.create_index(op.f("ix_trading_decision_logs_user_id"), "trading_decision_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_trading_decision_logs_user_id"), table_name="trading_decision_logs")
    op.drop_index(op.f("ix_trading_decision_logs_trade_date"), table_name="trading_decision_logs")
    op.drop_index(op.f("ix_trading_decision_logs_ticker"), table_name="trading_decision_logs")
    op.drop_index(op.f("ix_trading_decision_logs_asset_id"), table_name="trading_decision_logs")
    op.drop_index(op.f("ix_trading_decision_logs_analysis_result_id"), table_name="trading_decision_logs")
    op.drop_index("ix_trading_decision_ticker_settled", table_name="trading_decision_logs")
    op.drop_index("ix_trading_decision_asset_date", table_name="trading_decision_logs")
    op.drop_table("trading_decision_logs")
