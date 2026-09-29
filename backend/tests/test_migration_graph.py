"""The Alembic history must have unique revisions and one upgrade head."""

import unittest
from pathlib import Path

from alembic.script import ScriptDirectory


class MigrationGraphTests(unittest.TestCase):
    def test_worker_app_and_ticket_classification_migrations_merge_into_one_head(self):
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        script = ScriptDirectory(str(migrations))

        self.assertEqual(script.get_heads(), ["0034"])
        self.assertEqual(
            script.get_revision("0034").down_revision,
            ("0033", "0033_worker_app_api"),
        )
