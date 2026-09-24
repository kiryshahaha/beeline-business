"""HTTP coverage for the global activity feed and role-based visibility."""

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.modules.notifications.enums import NotificationKind
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase

BASE_TIME = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def minutes(count: int) -> datetime:
    return BASE_TIME + timedelta(minutes=count)


class RecentActivityApiTests(DatabaseTestCase):
    """Exercise the feed against an isolated PostgreSQL schema."""

    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.addCleanup(lambda: app.dependency_overrides.pop(get_current_user, None))
        self.client = self.enterContext(TestClient(app))

        self.observer = self.create_user("observer", UserRole.OBSERVER)
        self.second_observer = self.create_user("observer_two", UserRole.OBSERVER)
        self.foreman_one = self.create_user("foreman_one", UserRole.FOREMAN)
        self.foreman_two = self.create_user("foreman_two", UserRole.FOREMAN)
        self.foreman_without_brigade = self.create_user("foreman_free", UserRole.FOREMAN)
        self.worker_one = self.create_user("worker_one", UserRole.WORKER)
        self.worker_two = self.create_user("worker_two", UserRole.WORKER)

        self.location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:building_id) RETURNING id"),
            {"building_id": self.create_building()},
        ).scalar_one()
        office_id = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) "
                "VALUES ('Офис аналитики', :location_id) RETURNING id"
            ),
            {"location_id": self.location_id},
        ).scalar_one()
        self.create_brigade("Альфа", self.foreman_one.id, office_id, self.worker_one.id)
        self.create_brigade("Бета", self.foreman_two.id, office_id, self.worker_two.id)

        self.ticket_one = self.add_ticket("Монтаж оборудования", minutes(0), self.worker_one.id)
        self.ticket_two = self.add_ticket("Ремонт у клиента", minutes(1), self.worker_two.id)
        self.add_event(
            self.ticket_one,
            NotificationKind.TICKET_ASSIGNED,
            minutes(2),
            {"title": "Монтаж оборудования", "worker_id": self.worker_one.id},
            [self.worker_one.id],
        )
        # One status change is stored once per observer; the feed must show it once.
        self.add_event(
            self.ticket_one,
            NotificationKind.TICKET_STATUS_CHANGED,
            minutes(5),
            {
                "title": "Монтаж оборудования",
                "previous_status": TicketStatus.PLANNED.value,
                "status": TicketStatus.IN_PROGRESS.value,
                "actor_id": self.worker_one.id,
            },
            [self.observer.id, self.second_observer.id],
        )
        self.comment_id = self.add_comment(
            self.ticket_one, self.observer.id, "Клиент просит позвонить за час", minutes(6)
        )
        self.add_comment(
            self.ticket_one,
            self.observer.id,
            "Клиент просит позвонить за час, домофон не работает",
            minutes(6),
            updated_at=minutes(7),
            comment_id=self.comment_id,
        )
        self.long_comment_id = self.add_comment(
            self.ticket_two, self.foreman_two.id, ("Длинный текст. " * 20).strip(), minutes(8)
        )
        self.session.commit()
        self.current_user = self.observer

    def create_user(self, username: str, role: UserRole):
        worker_profile = None
        if role == UserRole.WORKER:
            worker_profile = WorkerProfileCreate(
                workshift_start="09:00:00", workshift_end="18:00:00", skills=["Монтаж"]
            )
        return create_user(
            self.session,
            UserCreate(
                name="Иван",
                surname=username.capitalize(),
                username=username,
                password="Password123!",
                role=role,
                worker_profile=worker_profile,
            ),
        )

    def create_building(self) -> int:
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text("INSERT INTO streets (name, city_id) VALUES ('Улица', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        district_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Район', :city_id) RETURNING id"),
            {"city_id": city_id},
        ).scalar_one()
        return self.connection.execute(
            text(
                "INSERT INTO buildings (city_id, street_id, district_id, number) "
                "VALUES (:city_id, :street_id, :district_id, '1') RETURNING id"
            ),
            {"city_id": city_id, "street_id": street_id, "district_id": district_id},
        ).scalar_one()

    def create_brigade(self, name: str, foreman_id: int, office_id: int, worker_id: int) -> int:
        brigade_id = self.connection.execute(
            text(
                "INSERT INTO brigades (name, foreman_id, office_id) "
                "VALUES (:name, :foreman_id, :office_id) RETURNING id"
            ),
            {"name": name, "foreman_id": foreman_id, "office_id": office_id},
        ).scalar_one()
        self.connection.execute(
            text(
                "INSERT INTO brigade_members (brigade_id, worker_id) "
                "VALUES (:brigade_id, :worker_id)"
            ),
            {"brigade_id": brigade_id, "worker_id": worker_id},
        )
        return brigade_id

    def add_ticket(self, title: str, created_at: datetime, worker_id: int | None = None) -> int:
        ticket_id = self.connection.execute(
            text(
                "INSERT INTO tickets ("
                "location_id, title, work_type, status, visit_window_start, visit_window_end, "
                "estimated_duration_minutes, created_at, updated_at"
                ") VALUES ("
                ":location_id, :title, 'Настройка сети', 'planned', :visit_start, :visit_end, "
                "60, :created_at, :created_at"
                ") RETURNING id"
            ),
            {
                "location_id": self.location_id,
                "title": title,
                "visit_start": created_at,
                "visit_end": created_at + timedelta(hours=4),
                "created_at": created_at,
            },
        ).scalar_one()
        if worker_id is not None:
            self.connection.execute(
                text("UPDATE tickets SET assigned_worker_id = :worker_id WHERE id = :ticket_id"),
                {"ticket_id": ticket_id, "worker_id": worker_id},
            )
        return ticket_id

    def add_event(
        self,
        ticket_id: int,
        kind: NotificationKind,
        created_at: datetime,
        data: dict,
        recipient_ids: list[int],
    ) -> None:
        for recipient_id in recipient_ids:
            self.connection.execute(
                text(
                    "INSERT INTO notification_events "
                    "(recipient_id, ticket_id, kind, data, created_at) "
                    "VALUES (:recipient_id, :ticket_id, :kind, CAST(:data AS JSONB), :created_at)"
                ),
                {
                    "recipient_id": recipient_id,
                    "ticket_id": ticket_id,
                    "kind": kind.value,
                    "data": json.dumps(data, ensure_ascii=False),
                    "created_at": created_at,
                },
            )

    def add_comment(
        self,
        ticket_id: int,
        author_id: int,
        body: str,
        created_at: datetime,
        updated_at: datetime | None = None,
        comment_id: int | None = None,
    ) -> int:
        if comment_id is not None:
            self.connection.execute(
                text(
                    "UPDATE ticket_comments SET text = :text, updated_at = :updated_at "
                    "WHERE id = :id"
                ),
                {"text": body, "updated_at": updated_at, "id": comment_id},
            )
            return comment_id
        return self.connection.execute(
            text(
                "INSERT INTO ticket_comments (ticket_id, author_id, text, created_at, updated_at) "
                "VALUES (:ticket_id, :author_id, :text, :created_at, :updated_at) RETURNING id"
            ),
            {
                "ticket_id": ticket_id,
                "author_id": author_id,
                "text": body,
                "created_at": created_at,
                "updated_at": updated_at or created_at,
            },
        ).scalar_one()

    def feed(self, **params):
        response = self.client.get("/api/v1/analytics/recent-activity", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_feed_returns_every_source_newest_first(self):
        items = self.feed()

        self.assertEqual(
            [(item["kind"], item["ticket"]["id"]) for item in items],
            [
                ("comment_added", self.ticket_two),
                ("comment_edited", self.ticket_one),
                ("comment_added", self.ticket_one),
                ("ticket_status_changed", self.ticket_one),
                ("ticket_assigned", self.ticket_one),
                ("ticket_created", self.ticket_two),
                ("ticket_created", self.ticket_one),
            ],
        )

    def test_status_change_is_shown_once_with_its_actor(self):
        items = [item for item in self.feed() if item["kind"] == "ticket_status_changed"]

        self.assertEqual(len(items), 1)
        (item,) = items
        self.assertEqual(datetime.fromisoformat(item["occurred_at"]), minutes(5))
        self.assertEqual(item["ticket"]["title"], "Монтаж оборудования")
        self.assertEqual(
            item["actor"],
            {"id": self.worker_one.id, "full_name": "Worker_one Иван", "role": "worker"},
        )
        self.assertEqual(item["details"]["previous_status"], "planned")
        self.assertEqual(item["details"]["status"], "in_progress")
        self.assertIsNone(item["details"]["comment_id"])

    def test_assignment_names_the_worker_without_an_actor(self):
        (item,) = [item for item in self.feed() if item["kind"] == "ticket_assigned"]

        self.assertIsNone(item["actor"])
        self.assertEqual(
            item["details"]["worker"],
            {"id": self.worker_one.id, "full_name": "Worker_one Иван", "role": "worker"},
        )

    def test_created_ticket_has_no_actor_because_it_is_not_recorded(self):
        items = [item for item in self.feed() if item["kind"] == "ticket_created"]

        self.assertEqual([item["actor"] for item in items], [None, None])
        self.assertEqual(items[0]["ticket"]["status"], "planned")

    def test_comment_events_carry_author_and_shortened_text(self):
        added = next(
            item
            for item in self.feed()
            if item["kind"] == "comment_added" and item["ticket"]["id"] == self.ticket_one
        )
        edited = next(item for item in self.feed() if item["kind"] == "comment_edited")
        long_comment = next(
            item
            for item in self.feed()
            if item["kind"] == "comment_added" and item["ticket"]["id"] == self.ticket_two
        )

        self.assertEqual(added["actor"]["id"], self.observer.id)
        self.assertEqual(added["details"]["comment_id"], self.comment_id)
        self.assertEqual(
            added["details"]["comment_excerpt"],
            "Клиент просит позвонить за час, домофон не работает",
        )
        self.assertEqual(edited["details"]["comment_id"], self.comment_id)
        self.assertEqual(datetime.fromisoformat(edited["occurred_at"]), minutes(7))
        self.assertEqual(
            long_comment["details"]["comment_excerpt"], "Длинный текст. " * 9 + "Длинн…"
        )

    def test_pagination_walks_the_feed_without_repeats(self):
        first_page = self.feed(limit=3)
        second_page = self.feed(limit=3, offset=3)

        self.assertEqual(len(first_page), 3)
        self.assertEqual(first_page, self.feed()[:3])
        self.assertEqual(second_page, self.feed()[3:6])

    def test_invalid_pagination_is_rejected(self):
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "many"}):
            with self.subTest(params=params):
                response = self.client.get("/api/v1/analytics/recent-activity", params=params)
                self.assertEqual(response.status_code, 422)

    def test_foreman_sees_only_tickets_of_own_brigade(self):
        self.current_user = self.foreman_one
        own = self.feed()

        self.assertEqual({item["ticket"]["id"] for item in own}, {self.ticket_one})

        self.current_user = self.foreman_two
        self.assertEqual({item["ticket"]["id"] for item in self.feed()}, {self.ticket_two})

        self.current_user = self.foreman_without_brigade
        self.assertEqual(self.feed(), [])

    def test_worker_is_forbidden_and_token_is_required(self):
        self.current_user = self.worker_one
        forbidden = self.client.get("/api/v1/analytics/recent-activity")
        self.assertEqual(forbidden.status_code, 403)

        app.dependency_overrides.pop(get_current_user, None)
        unauthorized = self.client.get("/api/v1/analytics/recent-activity")
        self.assertEqual(unauthorized.status_code, 401)

    def test_real_api_actions_appear_in_the_feed(self):
        created = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.location_id,
                "title": "Свежая заявка",
                "work_type": "Настройка сети",
                "visit_window_start": "2026-09-21T10:00:00+03:00",
                "visit_window_end": "2026-09-21T14:00:00+03:00",
                "estimated_duration_minutes": 60,
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        ticket_id = created.json()["id"]
        self.assertEqual(
            self.client.put(
                f"/api/v1/tickets/{ticket_id}/assignees",
                json={"worker_id": self.worker_one.id},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/tickets/{ticket_id}/status", json={"status": "in_progress"}
            ).status_code,
            200,
        )
        comment = self.client.post(
            f"/api/v1/tickets/{ticket_id}/comments", json={"text": "Выехали на объект"}
        )
        self.assertEqual(comment.status_code, 201, comment.text)

        kinds = {item["kind"] for item in self.feed(limit=100) if item["ticket"]["id"] == ticket_id}

        self.assertEqual(
            kinds,
            {"ticket_created", "ticket_assigned", "ticket_status_changed", "comment_added"},
        )
