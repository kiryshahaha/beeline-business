"""Temporary migrated schemas for end-to-end tests; never target application data."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema


@contextmanager
def migrated_schema(admin_engine, revision="head"):
    """Create/drop only a newly generated schema in the already verified test database."""
    name = "beeline_exchange_" + uuid4().hex
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(name))
    engine = create_engine(admin_engine.url, connect_args={"options": f"-csearch_path={name}"})
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
        yield engine, config
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(name, cascade=True))
