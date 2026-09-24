"""Brigade ticket filters and scoped foreman access."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import Building, City, District, Location, Office, Street
from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class BrigadeTicketVisibilityTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Город"))
        district = self.save(District(city_id=city.id, name="Район"))
        street = self.save(Street(city_id=city.id, name="Улица"))
        building = self.save(
            Building(city_id=city.id, district_id=district.id, street_id=street.id, number="1")
        )
        self.location_id = self.save(Location(building_id=building.id)).id
        self.office_id = self.save(Office(location_id=self.location_id, name="Офис")).id
        self.city_id, self.district_id = city.id, district.id
        self.session.commit()
        self.observer = self.new_user("observer", UserRole.OBSERVER)
        self.foreman = self.new_user("foreman", UserRole.FOREMAN)
        self.other_foreman = self.new_user("other_foreman", UserRole.FOREMAN)
        self.lonely_foreman = self.new_user("lonely_foreman", UserRole.FOREMAN)
        self.worker = self.new_user("worker", UserRole.WORKER)
        self.coworker = self.new_user("coworker", UserRole.WORKER)
        self.other_worker = self.new_user("other_worker", UserRole.WORKER)

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))
        self.own_brigade = self.new_brigade(self.foreman, [self.worker, self.coworker])
        self.other_brigade = self.new_brigade(self.other_foreman, [self.other_worker])
        # Foreign and unassigned tickets precede own tickets to test SQL pagination.
        self.foreign_ticket = self.new_ticket([self.other_worker])
        self.unassigned_ticket = self.new_ticket([])
        self.own_ticket = self.new_ticket([self.worker])

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def new_user(self, username, role):
        return create_user(
            self.session,
            UserCreate(
                name="Тест",
                surname=username,
                username=username,
                password="Password123!",
                role=role,
                worker_profile=WorkerProfileCreate(
                    workshift_start="09:00", workshift_end="18:00", skills=["Диагностика"]
                )
                if role == UserRole.WORKER
                else None,
            ),
        )

    @staticmethod
    def auth(user):
        return {
            "Authorization": "Bearer "
            + create_access_token({"sub": str(user.id), "role": user.role.value})
        }

    def new_brigade(self, foreman, workers):
        response = self.client.post(
            "/api/v1/brigades",
            headers=self.auth(self.observer),
            json={
                "name": foreman.username,
                "foreman_id": foreman.id,
                "office_id": self.office_id,
                "worker_ids": [worker.id for worker in workers],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def new_ticket(self, workers):
        response = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.location_id,
                "title": "Проверить линию",
                "work_type": "Диагностика",
                "visit_window_start": "2026-09-14T10:00:00+03:00",
                "visit_window_end": "2026-09-14T14:00:00+03:00",
                "estimated_duration_minutes": 60,
            },
            headers=self.auth(self.observer),
        )
        self.assertEqual(response.status_code, 201, response.text)
        ticket_id = response.json()["id"]
        response = self.client.put(
            f"/api/v1/tickets/{ticket_id}/assignees",
            headers=self.auth(self.observer),
            json={"worker_id": workers[0].id if workers else None},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return ticket_id

    def listed_ids(self, user=None, **params):
        response = self.client.get(
            "/api/v1/tickets", params=params, headers=self.auth(user) if user else {}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return [ticket["id"] for ticket in response.json()]

    def test_observer_keeps_global_reads_and_brigade_filter(self):
        self.assertEqual(
            self.listed_ids(self.observer),
            [
                self.foreign_ticket,
                self.unassigned_ticket,
                self.own_ticket,
            ],
        )
        self.assertEqual(
            self.listed_ids(self.observer, brigade_id=self.own_brigade),
            [self.own_ticket],
        )
        response = self.client.get(
            f"/api/v1/tickets/{self.foreign_ticket}", headers=self.auth(self.observer)
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_worker_reads_only_assigned_tickets_in_lists_and_by_id(self):
        self.assertEqual(self.listed_ids(self.worker), [self.own_ticket])
        self.assertEqual(
            self.listed_ids(
                self.worker,
                status="planned",
                city_id=self.city_id,
                district_id=self.district_id,
                brigade_id=self.own_brigade,
            ),
            [self.own_ticket],
        )
        for ticket_id in (self.own_ticket,):
            response = self.client.get(
                f"/api/v1/tickets/{ticket_id}", headers=self.auth(self.worker)
            )
            self.assertEqual(response.status_code, 200, response.text)
        for ticket_id in (self.foreign_ticket, self.unassigned_ticket, 2147483647):
            response = self.client.get(
                f"/api/v1/tickets/{ticket_id}", headers=self.auth(self.worker)
            )
            self.assertEqual(response.status_code, 404, response.text)

    def test_foreman_scope_is_intersected_with_filter_before_pagination(self):
        self.assertEqual(self.listed_ids(self.foreman), [self.own_ticket])
        self.assertEqual(self.listed_ids(self.foreman, brigade_id=self.other_brigade), [])
        self.assertEqual(self.listed_ids(self.foreman, limit=1, offset=0), [self.own_ticket])
        self.assertEqual(
            self.listed_ids(
                self.foreman,
                status="planned",
                city_id=self.city_id,
                district_id=self.district_id,
                brigade_id=self.own_brigade,
            ),
            [self.own_ticket],
        )
        self.assertEqual(self.listed_ids(self.foreman, status="completed"), [])
        self.assertEqual(self.listed_ids(self.lonely_foreman), [])
        self.assertEqual(self.listed_ids(self.foreman, brigade_id=2147483647), [])

    def test_foreman_detail_and_comment_feed_hide_foreign_or_unassigned_tickets(self):
        for ticket_id in (self.foreign_ticket, self.unassigned_ticket, 2147483647):
            for suffix in ("", "/comments"):
                response = self.client.get(
                    f"/api/v1/tickets/{ticket_id}{suffix}", headers=self.auth(self.foreman)
                )
                self.assertEqual(response.status_code, 404, response.text)
        for ticket_id in (self.own_ticket,):
            for suffix in ("", "/comments"):
                response = self.client.get(
                    f"/api/v1/tickets/{ticket_id}{suffix}", headers=self.auth(self.foreman)
                )
                self.assertEqual(response.status_code, 200, response.text)

    def test_foreman_can_create_comments_only_for_visible_brigade_tickets(self):
        url = f"/api/v1/tickets/{self.own_ticket}"
        response = self.client.post(
            url + "/comments", json={"text": "Заметка начальника"}, headers=self.auth(self.foreman)
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["text"], "Заметка начальника")
        self.assertEqual(response.json()["author"]["id"], self.foreman.id)
        self.assertEqual(response.json()["author"]["role"], "foreman")

        for ticket_id in (self.foreign_ticket, self.unassigned_ticket):
            denied = self.client.post(
                f"/api/v1/tickets/{ticket_id}/comments",
                json={"text": "Чужая заметка"},
                headers=self.auth(self.foreman),
            )
            self.assertEqual(denied.status_code, 404, denied.text)

    def test_foreman_can_edit_own_comment_but_not_another_authors_comment(self):
        url = f"/api/v1/tickets/{self.own_ticket}/comments"
        own_comment = self.client.post(
            url, json={"text": "Исходный"}, headers=self.auth(self.foreman)
        )
        self.assertEqual(own_comment.status_code, 201, own_comment.text)
        own_comment_id = own_comment.json()["id"]

        edited = self.client.patch(
            f"{url}/{own_comment_id}",
            json={"text": "Исправленный начальником"},
            headers=self.auth(self.foreman),
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["text"], "Исправленный начальником")
        self.assertEqual(edited.json()["author"]["id"], self.foreman.id)

        observer_comment = self.client.post(
            url, json={"text": "Комментарий наблюдателя"}, headers=self.auth(self.observer)
        )
        self.assertEqual(observer_comment.status_code, 201, observer_comment.text)
        denied = self.client.patch(
            f"{url}/{observer_comment.json()['id']}",
            json={"text": "Чужая правка"},
            headers=self.auth(self.foreman),
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_foreman_still_cannot_change_ticket_status(self):
        url = f"/api/v1/tickets/{self.own_ticket}"
        response = self.client.patch(
            url + "/status",
            json={"status": "completed"},
            headers=self.auth(self.foreman),
        )
        self.assertEqual(response.status_code, 403, response.text)
        current = self.client.get(url, headers=self.auth(self.observer))
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["status"], "planned")

    def test_supplied_invalid_credentials_do_not_fall_back_to_anonymous(self):
        for authorization in ("Bearer invalid", "Basic invalid", "Bearer"):
            for suffix in ("", f"/{self.own_ticket}"):
                response = self.client.get(
                    "/api/v1/tickets" + suffix, headers={"Authorization": authorization}
                )
                self.assertEqual(response.status_code, 401, response.text)

    def test_brigade_filter_validates_positive_int32(self):
        for value in (0, -1, 2147483648, "invalid"):
            response = self.client.get(
                "/api/v1/tickets",
                params={"brigade_id": value},
                headers=self.auth(self.observer),
            )
            self.assertEqual(response.status_code, 422, response.text)
