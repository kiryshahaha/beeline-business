"""Shared PostgreSQL test isolation; never uses the application's DATABASE_URL."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema


class DatabaseTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_url = os.getenv("TEST_DATABASE_URL")
        if not database_url:
            raise RuntimeError("TEST_DATABASE_URL is required for PostgreSQL integration tests")
        parsed_url = make_url(database_url)
        if parsed_url.get_backend_name() != "postgresql" or not (
            parsed_url.database or ""
        ).endswith("_test"):
            raise RuntimeError(
                "TEST_DATABASE_URL must point to a PostgreSQL database ending in _test"
            )

        cls.schema = "beeline_test_" + uuid4().hex
        cls.admin_engine = create_engine(database_url)
        cls.addClassCleanup(cls.admin_engine.dispose)
        with cls.admin_engine.begin() as connection:
            connection.execute(CreateSchema(cls.schema))
        cls.addClassCleanup(cls.drop_schema)
        cls.engine = create_engine(
            database_url, connect_args={"options": f"-csearch_path={cls.schema}"}
        )
        cls.addClassCleanup(cls.engine.dispose)

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with cls.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.downgrade(config, "base")
            if set(inspect(connection).get_table_names()) - {"alembic_version"}:
                raise AssertionError("Downgrade left domain tables behind")
            connection.commit()
            command.upgrade(config, "head")
            command.check(config)

    @classmethod
    def drop_schema(cls):
        with cls.admin_engine.begin() as connection:
            connection.execute(DropSchema(cls.schema, cascade=True))

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)
        self.addCleanup(self.session.close)


class CommittedDatabaseTestCase(DatabaseTestCase):
    """Allow real commits; reset only this class's isolated schema before each test."""

    def setUp(self):
        with self.engine.begin() as connection:
            if connection.execute(text("SELECT current_schema()")).scalar_one() != self.schema:
                raise RuntimeError("Refusing to reset tables outside the isolated test schema")
            connection.execute(
                text(
                    "TRUNCATE planning_plan_routes, planning_plans, work_type_required_skills, "
                    "work_type_required_appliances, work_type_planning_rules, "
                    "data_imports, routes, ticket_appliances, "
                    "appliance_stocks, appliances, "
                    "brigade_members, brigades, offices, notification_events, "
                    "push_subscriptions, ticket_comments, ticket_assignments, "
                    "tickets, refresh_tokens, calendar_tokens, worker_skill_assignments, "
                    "worker_skills, workers, users, locations, entrances, "
                    "buildings, streets, districts, cities"
                )
            )
