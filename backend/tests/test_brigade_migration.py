"""Database contract for brigade tables and user-role constraint."""

from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.modules.brigades.schemas import BrigadeMembersUpdate
from tests.support import DatabaseTestCase


class BrigadeMigrationTests(DatabaseTestCase):
    def test_brigade_tables_constraints_and_role_are_created(self):
        inspector = inspect(self.connection)
        self.assertIn("brigades", inspector.get_table_names())
        self.assertIn("brigade_members", inspector.get_table_names())

        brigade_indexes = inspector.get_indexes("brigades")
        member_indexes = inspector.get_indexes("brigade_members")
        self.assertIn("uq_brigades_foreman_id", [index["name"] for index in brigade_indexes])
        self.assertIn("uq_brigade_members_worker_id", [index["name"] for index in member_indexes])

        foreman_id = self.connection.execute(
            text(
                """
                INSERT INTO users (name, surname, username, password_hash, role)
                VALUES ('Бригадир', 'Тестов', 'foreman_test', 'hash', 'foreman')
                RETURNING id
                """
            )
        ).scalar_one()
        second_foreman_id = self.connection.execute(
            text(
                """
                INSERT INTO users (name, surname, username, password_hash, role)
                VALUES ('Бригадир', 'Второй', 'foreman_second', 'hash', 'foreman')
                RETURNING id
                """
            )
        ).scalar_one()
        worker_id = self.connection.execute(
            text(
                """
                INSERT INTO users (name, surname, username, password_hash, role)
                VALUES ('Работник', 'Тестов', 'worker_test', 'hash', 'worker')
                RETURNING id
                """
            )
        ).scalar_one()
        self.connection.execute(
            text(
                """
                INSERT INTO workers (user_id, workshift_start, workshift_end)
                VALUES (:worker_id, '09:00', '18:00')
                """
            ),
            {"worker_id": worker_id},
        )
        brigade_id = self.connection.execute(
            text(
                """
                INSERT INTO brigades (name, foreman_id)
                VALUES ('Бригада 1', :foreman_id)
                RETURNING id
                """
            ),
            {"foreman_id": foreman_id},
        ).scalar_one()
        self.connection.execute(
            text(
                """
                INSERT INTO brigade_members (brigade_id, worker_id)
                VALUES (:brigade_id, :worker_id)
                """
            ),
            {"brigade_id": brigade_id, "worker_id": worker_id},
        )

        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(
                    text(
                        """
                        INSERT INTO brigade_members (brigade_id, worker_id)
                        VALUES (:brigade_id, :worker_id)
                        """
                    ),
                    {"brigade_id": brigade_id, "worker_id": worker_id},
                )

        second_brigade_id = self.connection.execute(
            text(
                """
                INSERT INTO brigades (name, foreman_id)
                VALUES ('Бригада 2', :foreman_id)
                RETURNING id
                """
            ),
            {"foreman_id": second_foreman_id},
        ).scalar_one()
        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(
                    text(
                        """
                        INSERT INTO brigade_members (brigade_id, worker_id)
                        VALUES (:brigade_id, :worker_id)
                        """
                    ),
                    {"brigade_id": second_brigade_id, "worker_id": worker_id},
                )

        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(
                    text(
                        """
                        INSERT INTO users (name, surname, username, password_hash, role)
                        VALUES ('Неверный', 'Тестов', 'invalid_role', 'hash', 'administrator')
                        """
                    )
                )

    def test_members_update_requires_foreman_id(self):
        with self.assertRaises(ValidationError):
            BrigadeMembersUpdate(worker_ids=[1])

        payload = BrigadeMembersUpdate(foreman_id=1, worker_ids=[2, 3])
        self.assertEqual(payload.foreman_id, 1)
