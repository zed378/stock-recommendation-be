"""Alembic environment for the Trader, separate from the analysis platform's.

Its own version table lives inside schema `trading`, so the two histories can
never interfere (docs/03-DATA-MODEL/07). Migrations run as `trader_owner` at
deploy time; the running Trader's role cannot change the schema.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

import aidss_trader.db.models  # noqa: F401  (populates metadata)
from aidss_trader.db.base import SCHEMA, Base

config = context.config
url = os.environ.get("AIDSS_TRADER_MIGRATION_DATABASE_URL")
if not url:
    raise SystemExit("AIDSS_TRADER_MIGRATION_DATABASE_URL (role trader_owner) is required")

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
