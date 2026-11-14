"""Foundation: schema trading, credential, audit_log, lease, risk_limit, and their grants.

Additive only. Grants are part of the migration because the privilege boundary
is part of the design (ADR-021): the running role can append to the audit log
but never change it, and a risk-limit version is immutable once written.

Roles are cluster objects and are created once by `deploy/trader/bootstrap.sql`
(run by a superuser); this migration only grants to them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import aidss_trader.db.models  # noqa: F401
from aidss_trader.db.base import SCHEMA, Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

_FOUNDATION_TABLES = ("credential", "audit_log", "lease", "risk_limit")


def _tables(names):
    return [Base.metadata.tables[f"{SCHEMA}.{t}"] for t in names]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    Base.metadata.create_all(bind, tables=_tables(_FOUNDATION_TABLES))

    if bind.dialect.name != "postgresql":
        return

    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO trader_rw, trader_monitor")
    # Append-only: INSERT and SELECT, nothing else.
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.audit_log TO trader_rw")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {SCHEMA}.audit_log_seq_seq TO trader_rw")
    # A limits version is immutable once written.
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.risk_limit TO trader_rw")
    # Rotated and retired, so it may be updated; deleting history is not needed.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.credential TO trader_rw")
    # The lease is renewed, taken over, and released.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.lease TO trader_rw")
    # The host liveness script reads the heartbeat and nothing else (ADR-039).
    op.execute(f"GRANT SELECT ON {SCHEMA}.lease TO trader_monitor")


def downgrade() -> None:
    # Never against a database that holds live records (docs/03-DATA-MODEL/07);
    # present for development databases only.
    bind = op.get_bind()
    Base.metadata.drop_all(bind, tables=_tables(reversed(_FOUNDATION_TABLES)))
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA}"))
