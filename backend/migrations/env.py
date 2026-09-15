"""Alembic uses the same settings and model registry as the application."""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.db import models  # noqa: F401 - populate the shared metadata
from app.db.base import Base
from app.db.session import get_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(get_settings().database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_and_run(supplied_connection)
        return
    with get_engine().connect() as connection:
        configure_and_run(connection)


def configure_and_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
