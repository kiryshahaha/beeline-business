"""The required integration suite must reject missing and unsafe database URLs."""

import os
import unittest
from unittest.mock import patch

from tests.support import DatabaseTestCase


class RequiredDatabaseConfigurationTests(unittest.TestCase):
    def test_missing_database_url_fails_instead_of_skipping(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TEST_DATABASE_URL is required"):
                DatabaseTestCase.setUpClass()

    def test_non_postgresql_and_non_test_database_urls_fail_before_connecting(self):
        for url in (
            "sqlite:///backend_test.db",
            "postgresql+psycopg://localhost/beeline",
        ):
            with (
                self.subTest(url=url),
                patch.dict(os.environ, {"TEST_DATABASE_URL": url}, clear=True),
            ):
                with self.assertRaisesRegex(RuntimeError, "must point to a PostgreSQL"):
                    DatabaseTestCase.setUpClass()

    def test_malformed_database_url_raises_configuration_error(self):
        with patch.dict(os.environ, {"TEST_DATABASE_URL": "postgres://[invalid"}, clear=True):
            with self.assertRaises(Exception):
                DatabaseTestCase.setUpClass()
