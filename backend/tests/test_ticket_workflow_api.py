"""Assignment and status-change behavior with recipient-specific outbox events."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, Street
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class TicketWorkflowApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Санкт-Петербург"))
        district = self.save(District(city_id=city.id, name="Невский район"))
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(
                city_id=city.id,
                street_id=street.id,
                district_id=district.id,
                number="10",
            )
        )
        location = self.save(Location(building_id=building.id))
        self.location_id = location.id
        self.session.commit()

        self.observer = self.create_user("observer_one", UserRole.OBSERVER)
        self.second_observer = self.create_user("observer_two", UserRole.OBSERVER)
        self.worker = self.create_user("worker_one", UserRole.WORKER)
        self.other_worker = self.create_user("worker_two", UserRole.WORKER)
        self.session.commit()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        created = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.location_id,
                "title": "Настроить Wi-Fi",
                "work_type_id": 1,
                "visit_window_start": "2026-09-14T10:00:00+03:00",
                "visit_window_end": "2026-09-14T14:00:00+03:00",
                "estimated_duration_minutes": 60,
            },
            headers=self.auth(self.observer),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.ticket_id = created.json()["id"]

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def create_user(self, username, role):
        profile = None
        if role == UserRole.WORKER:
            profile = WorkerProfileCreate(
                workshift_start="09:00:00",
                workshift_end="18:00:00",
                skills=["Настройка сети"],
            )
        return create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname=username,
                username=username,
                password="Password123!",
                role=role,
                worker_profile=profile,
            ),
        )

    @staticmethod
    def auth(user):
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}

    def events(self):
        return list(
            self.session.execute(
                text("""
                    SELECT recipient_id, ticket_id, kind, data
                    FROM notification_events
                    ORDER BY id
                """)
            )
            .mappings()
            .all()
        )

    def test_observer_replaces_assignees_and_only_new_workers_receive_events(self):
        url = f"/api/v1/tickets/{self.ticket_id}/assignees"
        response = self.client.put(
            url,
            json={"worker_id": self.worker.id},
            headers=self.auth(self.observer),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["assigned_worker_id"], self.worker.id)
        self.assertEqual(
            [(event["recipient_id"], event["kind"]) for event in self.events()],
            [(self.worker.id, "ticket_assigned")],
        )

        repeated = self.client.put(
            url,
            json={"worker_id": self.worker.id},
            headers=self.auth(self.observer),
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(len(self.events()), 1)

        expanded = self.client.put(
            url,
            json={"worker_id": self.other_worker.id},
            headers=self.auth(self.observer),
        )
        self.assertEqual(expanded.status_code, 200, expanded.text)
        self.assertEqual(expanded.json()["assigned_worker_id"], self.other_worker.id)
        self.assertEqual(
            [event["recipient_id"] for event in self.events()],
            [self.worker.id, self.other_worker.id],
        )

    def test_assignee_replacement_requires_observer_and_valid_workers(self):
        url = f"/api/v1/tickets/{self.ticket_id}/assignees"
        self.assertEqual(self.client.put(url, json={"worker_id": None}).status_code, 401)
        forbidden = self.client.put(
            url,
            json={"worker_id": self.worker.id},
            headers=self.auth(self.worker),
        )
        self.assertEqual(forbidden.status_code, 403)
        invalid = self.client.put(
            url,
            json={"worker_id": 2_147_483_647},
            headers=self.auth(self.observer),
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            invalid.json(), {"detail": "Один или несколько исполнителей не найдены или в архиве"}
        )
        missing = self.client.put(
            "/api/v1/tickets/2147483647/assignees",
            json={"worker_id": None},
            headers=self.auth(self.observer),
        )
        self.assertEqual(missing.status_code, 404)

    def test_status_change_notifies_every_observer_once(self):
        response = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": "in_progress"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "in_progress")
        events = self.events()
        self.assertEqual(
            {event["recipient_id"] for event in events},
            {self.observer.id, self.second_observer.id},
        )
        for event in events:
            self.assertEqual(event["kind"], "ticket_status_changed")
            self.assertEqual(event["ticket_id"], self.ticket_id)
            self.assertEqual(event["data"]["previous_status"], "planned")
            self.assertEqual(event["data"]["status"], "in_progress")
            self.assertEqual(event["data"]["actor_id"], self.observer.id)

        repeated = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": "in_progress"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(len(self.events()), 2)

    def test_only_observer_can_change_status(self):
        assign_url = f"/api/v1/tickets/{self.ticket_id}/assignees"
        assigned = self.client.put(
            assign_url,
            json={"worker_id": self.worker.id},
            headers=self.auth(self.observer),
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)

        denied = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": "in_progress"},
            headers=self.auth(self.other_worker),
        )
        self.assertEqual(denied.status_code, 403)
        worker_attempt = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": "in_progress"},
            headers=self.auth(self.worker),
        )
        self.assertEqual(worker_attempt.status_code, 403, worker_attempt.text)
        unchanged = self.client.get(
            f"/api/v1/tickets/{self.ticket_id}", headers=self.auth(self.observer)
        )
        self.assertEqual(unchanged.json()["status"], "planned")

        observer_attempt = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": "in_progress"},
            headers=self.auth(self.observer),
        )
        self.assertEqual(observer_attempt.status_code, 200, observer_attempt.text)

    def test_event_failure_rolls_back_status_change(self):
        with patch(
            "app.modules.tickets.repository.add_notification_events",
            side_effect=RuntimeError("outbox unavailable"),
            create=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
                self.client.patch(
                    f"/api/v1/tickets/{self.ticket_id}/status",
                    json={"status": "completed"},
                    headers=self.auth(self.observer),
                )
        fetched = self.client.get(
            f"/api/v1/tickets/{self.ticket_id}", headers=self.auth(self.observer)
        )
        self.assertEqual(fetched.json()["status"], "planned")
