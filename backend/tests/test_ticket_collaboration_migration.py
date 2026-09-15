"""Database contract for ticket collaboration and durable notifications."""

from sqlalchemy import inspect

from tests.support import DatabaseTestCase


class TicketCollaborationMigrationTests(DatabaseTestCase):
    def test_collaboration_tables_and_constraints_are_created(self):
        inspector = inspect(self.connection)
        expected_columns = {
            "ticket_assignments": {"ticket_id", "worker_id", "assigned_at"},
            "ticket_comments": {"id", "ticket_id", "author_id", "text", "created_at"},
            "push_subscriptions": {"id", "user_id", "token", "created_at", "updated_at"},
            "notification_events": {
                "id",
                "recipient_id",
                "ticket_id",
                "kind",
                "data",
                "created_at",
                "websocket_delivered_at",
                "push_delivered_at",
                "attempt_count",
                "next_attempt_at",
                "last_error",
            },
        }

        for table, columns in expected_columns.items():
            with self.subTest(table=table):
                self.assertIn(table, inspector.get_table_names())
                self.assertEqual(
                    {column["name"] for column in inspector.get_columns(table)},
                    columns,
                )

        if not set(expected_columns).issubset(inspector.get_table_names()):
            return

        assignment_pk = inspector.get_pk_constraint("ticket_assignments")
        self.assertEqual(set(assignment_pk["constrained_columns"]), {"ticket_id", "worker_id"})
        subscription_uniques = inspector.get_unique_constraints("push_subscriptions")
        self.assertIn(["token"], [item["column_names"] for item in subscription_uniques])
