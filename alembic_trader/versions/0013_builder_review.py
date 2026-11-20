"""Append-only Indodax builder context; additive, no runtime settings selected."""

from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0013_builder_review"
down_revision = "0012_signal_trade"
branch_labels = None
depends_on = None
_TABLES = ("builder_review",)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[f"{SCHEMA}.builder_review"]])
    if bind.dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.builder_review TO trader_rw")


def downgrade() -> None:
    raise RuntimeError("append-only evidence is not dropped by a downgrade")
