"""Alembic environment.

The database URL comes from application settings rather than alembic.ini, so
there is exactly one place credentials are read (Section 13).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Importing the models package populates Base.metadata; autogenerate is blind
# without it.
import aidss.db.models  # noqa: F401
from aidss.config import get_settings
from aidss.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> bool:
    """Make autogenerate emit an import for our custom column types.

    Alembic renders a user-defined type by its fully qualified name
    (``aidss.db.base.GUID()``) but does not add the import that name needs, so
    the generated migration fails with a NameError. Returning False keeps the
    default rendering; the side effect of registering the import is the point.
    """
    if type_ == "type" and type(obj).__module__.startswith("aidss."):
        autogen_context.imports.add("import aidss.db.base")  # type: ignore[attr-defined]
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_item=render_item,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Required by the vector columns on knowledge_chunks and
            # news_embeddings (Phase 7); creating it here keeps a fresh
            # database bootstrappable in one command.
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
