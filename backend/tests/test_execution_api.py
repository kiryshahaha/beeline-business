"""Observer execution commands, day state and equipment ledger integration tests."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.models import (
    Appliance,
    ApplianceStock,
    Building,
    City,
    DayPlanRevision,
    District,
    Location,
    Office,
    Street,
    TicketAppliance,
)
from app.db.session import get_session
from app.main import app
from app.modules.appliances.enums import ApplianceType
from app.modules.planning import router as planning_api
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from app.modules.worker_app import router as worker_app_api
from tests.support import DatabaseTestCase


class ExecutionApiTests(DatabaseTestCase):
    route_date = date(2030, 1, 15)

    def setUp(self):
        super().setUp()
        city = self._save(City(name="Москва"))
        district = self._save(District(city_id=city.id, name="Район выполнения"))
        street = self._save(Street(city_id=city.id, name="Улица выполнения"))
        first_building = self._save(
            Building(
                city_id=city.id,
                service_area_id=self.service_area_for_district(district.id),
                street_id=street.id,
                number="1",
            )
        )
        second_building = self._save(
            Building(
                city_id=city.id,
                service_area_id=self.service_area_for_district(district.id),
                street_id=street.id,
                number="2",
            )
        )
        self.source_location_id = self._save(
            Location(
                building_id=first_building.id,
                latitude=55.75,
                longitude=37.61,
            )
        ).id
        self.destination_location_id = self._save(
            Location(
                building_id=second_building.id,
                latitude=55.76,
                longitude=37.62,
            )
        ).id
        self.service_area_id = self.service_area_for_district(district.id)
        self.office = self._save(
            Office(name="Офис выполнения", location_id=self.source_location_id)
        )
        self.session.commit()
        self.observer = self._user("execution_observer", UserRole.OBSERVER)
        self.worker = self._user("execution_worker", UserRole.WORKER)

        def session_dependency():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = session_dependency
        self.addCleanup(app.dependency_overrides.pop, get_session)
        app.dependency_overrides[planning_api.get_planning_engine] = lambda: self.engine
        self.addCleanup(app.dependency_overrides.pop, planning_api.get_planning_engine)
        self.client = self.enterContext(TestClient(app))

    def _save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def _user(self, username, role):
        return create_user(
            self.session,
            UserCreate(
                name="Иван",
                surname=username,
                username=username,
                password="Password123!",
                role=role,
                worker_profile=(
                    WorkerProfileCreate(
                        workshift_start="08:00:00",
                        workshift_end="18:00:00",
                        skills=["Монтаж"],
                        service_area_id=self.service_area_id,
                    )
                    if role == UserRole.WORKER
                    else None
                ),
            ),
        )

    @staticmethod
    def _auth(user):
        token = create_access_token({"sub": str(user.id), "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}

    def _ticket(self, *, title="Заявка выполнения"):
        response = self.client.post(
            "/api/v1/tickets",
            json={
                "location_id": self.destination_location_id,
                "title": title,
                "description": "Проверка execution API",
                "work_type_id": 1,
                "status": "planned",
                "visit_window_start": "2030-01-15T11:00:00+03:00",
                "visit_window_end": "2030-01-15T19:00:00+03:00",
                "planned_start_at": None,
                "planned_end_at": None,
                "estimated_duration_minutes": 60,
                "actual_duration_minutes": None,
            },
            headers=self._auth(self.observer),
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _assign(self, ticket_id):
        response = self.client.put(
            f"/api/v1/tickets/{ticket_id}/assignees",
            json={"worker_id": self.worker.id},
            headers=self._auth(self.observer),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _command(
        self,
        path,
        revision,
        key,
        occurred_at,
        *,
        worker=False,
        reason=None,
        **values,
    ):
        body = {
            "expected_revision": revision,
            "occurred_at": occurred_at,
            "payload": {},
            **values,
        }
        if worker:
            body["worker_id"] = self.worker.id
            if path.endswith("/complete"):
                body.setdefault("note", "Работы выполнены")
        if reason is not None:
            body["reason"] = reason
        return self.client.post(
            path,
            json=body,
            headers=self._auth(self.observer) | {"Idempotency-Key": key},
        )

    def test_worker_actions_completion_review_and_worker_day(self):
        ticket_id = self._ticket(title="Заявка мобильного исполнителя")["id"]
        self._assign(ticket_id)
        worker_headers = self._auth(self.worker) | {"Idempotency-Key": "worker-route-start"}
        started_route = self.client.post(
            f"/api/v1/tickets/{ticket_id}/start-route",
            json={
                "expected_revision": 2,
                "worker_id": self.worker.id,
                "occurred_at": "2000-01-01T00:00:00+00:00",
            },
            headers=worker_headers,
        )
        self.assertEqual(started_route.status_code, 200, started_route.text)
        self.assertEqual(started_route.json()["state"], "en_route")
        started = self.client.post(
            f"/api/v1/tickets/{ticket_id}/start",
            json={"expected_revision": 3, "location_id": self.destination_location_id},
            headers=self._auth(self.worker) | {"Idempotency-Key": "worker-work-start"},
        )
        self.assertEqual(started.status_code, 200, started.text)
        day_before_completion = self.client.get("/api/v1/me/day", headers=self._auth(self.worker))
        self.assertEqual(day_before_completion.status_code, 200, day_before_completion.text)
        day_ticket = next(
            ticket
            for ticket in day_before_completion.json()["tickets"]
            if ticket["id"] == ticket_id
        )
        self.assertIsNone(day_ticket["completion_review"])
        self.assertEqual(day_before_completion.json()["summary"]["awaiting_confirmation"], 0)
        problem = self.client.post(
            f"/api/v1/tickets/{ticket_id}/problem",
            json={"expected_revision": 4, "type": "no_access", "text": "Домофон не отвечает"},
            headers=self._auth(self.worker) | {"Idempotency-Key": "worker-problem"},
        )
        self.assertEqual(problem.status_code, 201, problem.text)
        self.assertIn("Проблема: no_access", problem.json()["comment"]["text"])
        self.assertEqual(
            self.session.execute(
                text("SELECT lifecycle_state FROM tickets WHERE id=:id"), {"id": ticket_id}
            ).scalar_one(),
            "in_progress",
        )
        self.assertEqual(
            self.session.execute(
                text(
                    "SELECT count(*) FROM work_events "
                    "WHERE ticket_id=:id AND event_type='problem_reported'"
                ),
                {"id": ticket_id},
            ).scalar_one(),
            1,
        )
        completed = self.client.post(
            f"/api/v1/tickets/{ticket_id}/complete",
            json={
                "expected_revision": 4,
                "note": "Заменён терминал",
                "actual_duration_minutes": 45,
            },
            headers=self._auth(self.worker) | {"Idempotency-Key": "worker-work-complete"},
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        state = self.session.execute(
            text("SELECT state FROM ticket_completion_reviews WHERE ticket_id=:id"),
            {"id": ticket_id},
        ).scalar_one()
        self.assertEqual(state, "pending")
        self.assertEqual(
            self.session.execute(
                text(
                    "SELECT count(*) FROM notification_events "
                    "WHERE ticket_id=:id AND kind='ticket_completion_requested'"
                ),
                {"id": ticket_id},
            ).scalar_one(),
            1,
        )
        confirmation = self.client.post(
            f"/api/v1/tickets/{ticket_id}/completion/confirm",
            json={"expected_revision": 5, "comment": "Проверено"},
            headers=self._auth(self.observer) | {"Idempotency-Key": "review-confirm"},
        )
        self.assertEqual(confirmation.status_code, 200, confirmation.text)
        replayed_confirmation = self.client.post(
            f"/api/v1/tickets/{ticket_id}/completion/confirm",
            json={"expected_revision": 5, "comment": "Проверено"},
            headers=self._auth(self.observer) | {"Idempotency-Key": "review-confirm"},
        )
        self.assertEqual(replayed_confirmation.status_code, 200, replayed_confirmation.text)
        self.assertEqual(
            self.session.execute(
                text(
                    "SELECT count(*) FROM notification_events "
                    "WHERE ticket_id=:id AND kind='ticket_completion_confirmed'"
                ),
                {"id": ticket_id},
            ).scalar_one(),
            1,
        )
        day = self.client.get("/api/v1/me/day", headers=self._auth(self.worker))
        self.assertEqual(day.status_code, 200, day.text)
        self.assertEqual(day.json()["worker"]["id"], self.worker.id)
        self.assertIn(ticket_id, [ticket["id"] for ticket in day.json()["tickets"]])

    def test_assistant_chat_forwards_only_validated_dialog_to_internal_service(self):
        settings = SimpleNamespace(
            assistant_enabled=True,
            assistant_url="http://assistant:8002",
            assistant_timeout_seconds=4,
        )
        response = MagicMock()
        response.json.return_value = {"answer": "Готово", "source_type": "facts"}
        client = MagicMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.post = AsyncMock(return_value=response)
        body = {
            "message": "Какой статус заявки?",
            "history": [{"role": "user", "content": "Здравствуйте"}],
        }
        with (
            patch.object(worker_app_api, "get_settings", return_value=settings),
            patch.object(worker_app_api.httpx, "AsyncClient", return_value=client),
        ):
            result = self.client.post(
                "/api/v1/assistant/chat",
                json=body,
                headers=self._auth(self.observer),
            )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"answer": "Готово", "source_type": "facts"})
        client.post.assert_awaited_once_with(
            "http://assistant:8002/api/v1/chat",
            json={
                "role": "observer",
                "message": body["message"],
                "history": body["history"],
                "context": {},
            },
        )

    def _progress_to_work(self, ticket_id):
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/dispatch",
                2,
                f"dispatch-{ticket_id}",
                "2030-01-15T12:00:00+03:00",
            ).status_code,
            200,
        )
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/start-route",
                3,
                f"route-{ticket_id}",
                "2030-01-15T13:00:00+03:00",
                worker=True,
                location_id=self.source_location_id,
            ).status_code,
            200,
        )
        response = self._command(
            f"/api/v1/tickets/{ticket_id}/start",
            4,
            f"start-{ticket_id}",
            "2030-01-15T14:00:00+03:00",
            worker=True,
            location_id=self.destination_location_id,
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_lifecycle_day_state_rejects_active_route_redirect(self):
        ticket = self._ticket()
        ticket_id = ticket["id"]
        self.assertEqual((ticket["state"], ticket["revision"]), ("waiting_assignment", 1))
        self.assertEqual(self._assign(ticket_id)["state"], "assigned")

        shifted = self._command(
            f"/api/v1/tickets/{ticket_id}/window-change",
            2,
            "lifecycle-window-change",
            "2030-01-15T11:30:00+03:00",
            reason="Клиент подтвердил новое окно",
            new_window_start="2030-01-15T12:00:00+03:00",
            new_window_end="2030-01-15T20:00:00+03:00",
        )
        self.assertEqual(shifted.status_code, 200, shifted.text)
        self.assertEqual(shifted.json()["revision"], 3)
        self.assertEqual(
            datetime.fromisoformat(shifted.json()["visit_window_end"]),
            datetime(2030, 1, 15, 17, tzinfo=UTC),
        )
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            window_event = (
                session.execute(
                    text(
                        "SELECT reason, payload FROM work_events "
                        "WHERE ticket_id=:ticket_id AND event_type='window_change'"
                    ),
                    {"ticket_id": ticket_id},
                )
                .mappings()
                .one()
            )
        self.assertEqual(window_event["reason"], "Клиент подтвердил новое окно")
        self.assertEqual(
            datetime.fromisoformat(window_event["payload"]["previous_window_end"]),
            datetime(2030, 1, 15, 16, tzinfo=UTC),
        )
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/dispatch",
                3,
                "lifecycle-dispatch",
                "2030-01-15T12:00:00+03:00",
            ).json()["state"],
            "dispatched",
        )
        route = self._command(
            f"/api/v1/tickets/{ticket_id}/start-route",
            4,
            "lifecycle-route",
            "2030-01-15T13:00:00+03:00",
            worker=True,
            location_id=self.source_location_id,
        )
        self.assertEqual(route.json()["state"], "en_route")

        self.session.add(
            DayPlanRevision(
                service_area_id=self.service_area_id,
                route_date=self.route_date,
                revision=1,
                actor_id=self.observer.id,
                fingerprint="a" * 64,
                diff={},
                result={},
                is_current=True,
            )
        )
        self.session.commit()
        before_day_state = self.client.get(
            f"/api/v1/workers/{self.worker.id}/day-state",
            params={
                "service_area_id": self.service_area_id,
                "date": self.route_date.isoformat(),
                "at": "2030-01-15T13:30:00+03:00",
            },
            headers=self._auth(self.observer),
        )
        self.assertEqual(before_day_state.status_code, 200, before_day_state.text)
        redirected = self.client.post(
            f"/api/v1/planning/days/{self.service_area_id}/{self.route_date}/redirect",
            json={
                "worker_id": self.worker.id,
                "current_ticket_id": ticket_id,
                "new_destination_id": self.source_location_id,
                "expected_day_revision": 1,
                "occurred_at": "2030-01-15T13:30:00+03:00",
                "reason": "Клиент подтвердил новый адрес",
            },
            headers=self._auth(self.observer) | {"Idempotency-Key": "lifecycle-redirect"},
        )
        self.assertEqual(redirected.status_code, 409, redirected.text)
        self.assertEqual(redirected.json()["detail"]["code"], "active_route_redirect_forbidden")
        day_state = self.client.get(
            f"/api/v1/workers/{self.worker.id}/day-state",
            params={
                "service_area_id": self.service_area_id,
                "date": self.route_date.isoformat(),
                "at": "2030-01-15T13:30:00+03:00",
            },
            headers=self._auth(self.observer),
        )
        self.assertEqual(day_state.status_code, 200, day_state.text)
        self.assertEqual(day_state.json()["current_destination_id"], self.destination_location_id)
        self.assertEqual(day_state.json()["current_ticket_id"], ticket_id)
        self.assertEqual(day_state.json()["revision"], before_day_state.json()["revision"])
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            redirect_count = session.execute(
                text("SELECT count(*) FROM work_events WHERE event_type='redirect'")
            ).scalar_one()
            current_revision = session.execute(
                text(
                    "SELECT revision FROM day_plan_revisions "
                    "WHERE service_area_id=:area AND route_date=:route_date AND is_current"
                ),
                {"area": self.service_area_id, "route_date": self.route_date},
            ).scalar_one()
        self.assertEqual(redirect_count, 0)
        self.assertEqual(current_revision, 1)
        redirect_replay = self.client.post(
            f"/api/v1/planning/days/{self.service_area_id}/{self.route_date}/redirect",
            json={
                "worker_id": self.worker.id,
                "current_ticket_id": ticket_id,
                "new_destination_id": self.source_location_id,
                "expected_day_revision": 1,
                "occurred_at": "2030-01-15T13:30:00+03:00",
                "reason": "Клиент подтвердил новый адрес",
            },
            headers=self._auth(self.observer) | {"Idempotency-Key": "lifecycle-redirect"},
        )
        self.assertEqual(redirect_replay.status_code, 409, redirect_replay.text)
        self.assertEqual(
            redirect_replay.json()["detail"]["code"], "active_route_redirect_forbidden"
        )

        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/start",
                5,
                "lifecycle-start",
                "2030-01-15T14:00:00+03:00",
                worker=True,
                location_id=self.source_location_id,
            ).json()["state"],
            "in_progress",
        )
        delay = self._command(
            f"/api/v1/tickets/{ticket_id}/delay",
            6,
            "lifecycle-delay",
            "2030-01-15T15:00:00+03:00",
            worker=True,
            reason="Работа заняла больше времени",
            expected_available_at="2030-01-15T17:00:00+03:00",
        )
        self.assertEqual(delay.status_code, 200, delay.text)
        complete = self._command(
            f"/api/v1/tickets/{ticket_id}/complete",
            7,
            "lifecycle-complete",
            "2030-01-15T18:00:00+03:00",
            worker=True,
            location_id=self.source_location_id,
        )
        self.assertEqual(complete.json()["state"], "completed")

        before = self.client.get(
            f"/api/v1/workers/{self.worker.id}/day-state",
            params={
                "service_area_id": self.service_area_id,
                "date": self.route_date.isoformat(),
                "at": "2030-01-15T13:15:00+03:00",
            },
            headers=self._auth(self.observer),
        )
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["current_ticket_id"], ticket_id)
        self.assertEqual(before.json()["last_location_id"], self.source_location_id)

        replay = self._command(
            f"/api/v1/tickets/{ticket_id}/complete",
            7,
            "lifecycle-complete",
            "2030-01-15T18:00:00+03:00",
            worker=True,
            location_id=self.source_location_id,
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        reopened = self._command(
            f"/api/v1/tickets/{ticket_id}/reopen",
            8,
            "lifecycle-reopen",
            "2030-01-15T19:00:00+03:00",
            reason="Повторный выезд подтверждён",
        )
        self.assertEqual(
            (reopened.json()["state"], reopened.json()["execution_cycle"]),
            ("waiting_assignment", 2),
        )
        cancelled = self._command(
            f"/api/v1/tickets/{ticket_id}/cancel",
            9,
            "lifecycle-cancel",
            "2030-01-15T20:00:00+03:00",
            reason="Клиент отменил визит",
        )
        self.assertEqual(cancelled.json()["state"], "cancelled")
        invalid_legacy_transition = self.client.patch(
            f"/api/v1/tickets/{ticket_id}/status",
            json={"status": "in_progress"},
            headers=self._auth(self.observer),
        )
        self.assertEqual(invalid_legacy_transition.status_code, 409)
        self.assertEqual(invalid_legacy_transition.json()["detail"]["code"], "invalid_transition")
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            event_types = (
                session.execute(
                    text(
                        "SELECT event_type FROM work_events WHERE ticket_id=:ticket_id ORDER BY id"
                    ),
                    {"ticket_id": ticket_id},
                )
                .scalars()
                .all()
            )
        self.assertEqual(
            event_types,
            [
                "new_ticket",
                "assign",
                "window_change",
                "dispatch",
                "start_route",
                "start",
                "progress_delay",
                "complete",
                "reopen",
                "cancel_ticket",
            ],
        )

    def test_stale_revision_and_reused_idempotency_key_are_conflicts(self):
        ticket_id = self._ticket()["id"]
        self._assign(ticket_id)
        first = self._command(
            f"/api/v1/tickets/{ticket_id}/dispatch",
            2,
            "same-command-key",
            "2030-01-15T12:00:00+03:00",
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/dispatch",
                2,
                "same-command-key",
                "2030-01-15T12:00:00+03:00",
            ).status_code,
            200,
        )
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/start-route",
                3,
                "same-command-key",
                "2030-01-15T13:00:00+03:00",
                worker=True,
            ).status_code,
            409,
        )
        stale = self._command(
            f"/api/v1/tickets/{ticket_id}/start-route",
            2,
            "stale-command",
            "2030-01-15T13:00:00+03:00",
            worker=True,
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "stale_revision")

    def test_observer_only_commands_require_key_and_reason(self):
        ticket_id = self._ticket()["id"]
        self._assign(ticket_id)
        worker_headers = self._auth(self.worker)
        denied = self.client.post(
            f"/api/v1/tickets/{ticket_id}/dispatch",
            json={"expected_revision": 2},
            headers=worker_headers | {"Idempotency-Key": "worker-command"},
        )
        self.assertEqual(denied.status_code, 403)
        missing_key = self.client.post(
            f"/api/v1/tickets/{ticket_id}/dispatch",
            json={"expected_revision": 2},
            headers=self._auth(self.observer),
        )
        self.assertEqual(missing_key.status_code, 422)
        missing_reason = self._command(
            f"/api/v1/tickets/{ticket_id}/cancel",
            2,
            "missing-cancel-reason",
            "2030-01-15T12:00:00+03:00",
        )
        self.assertEqual(missing_reason.status_code, 422)

    def test_worker_unavailable_releases_planned_assignment_until_shift_end(self):
        ticket_id = self._ticket()["id"]
        self._assign(ticket_id)
        response = self.client.post(
            f"/api/v1/workers/{self.worker.id}/unavailable",
            json={
                "expected_revision": 1,
                "service_area_id": self.service_area_id,
                "route_date": self.route_date.isoformat(),
                "occurred_at": "2030-01-15T15:00:00+03:00",
                "worker_id": self.worker.id,
                "reason": "Инженер сообщил о недоступности",
                "payload": {},
            },
            headers=self._auth(self.observer) | {"Idempotency-Key": "worker-unavailable"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["available"])
        self.assertEqual(
            datetime.fromisoformat(body["unavailable_until"]).astimezone(UTC),
            datetime(2030, 1, 15, 15, tzinfo=UTC),
        )
        self.assertEqual(
            self.session.execute(
                text(
                    "SELECT count(*) FROM tickets "
                    "WHERE id=:ticket_id AND assigned_worker_id IS NOT NULL"
                ),
                {"ticket_id": ticket_id},
            ).scalar_one(),
            0,
        )
        replay = self.client.post(
            f"/api/v1/workers/{self.worker.id}/unavailable",
            json={
                "expected_revision": 1,
                "service_area_id": self.service_area_id,
                "route_date": self.route_date.isoformat(),
                "occurred_at": "2030-01-15T15:00:00+03:00",
                "worker_id": self.worker.id,
                "reason": "Инженер сообщил о недоступности",
                "payload": {},
            },
            headers=self._auth(self.observer) | {"Idempotency-Key": "worker-unavailable"},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(
            self.session.execute(
                text("SELECT count(*) FROM work_events WHERE idempotency_key='worker-unavailable'")
            ).scalar_one(),
            1,
        )
        self.assertEqual(
            self.session.execute(
                text("SELECT lifecycle_state FROM tickets WHERE id=:ticket_id"),
                {"ticket_id": ticket_id},
            ).scalar_one(),
            "waiting_assignment",
        )
        self.assertEqual(
            self.session.execute(
                text(
                    "SELECT count(*) FROM work_events "
                    "WHERE ticket_id=:ticket_id AND event_type='unassign'"
                ),
                {"ticket_id": ticket_id},
            ).scalar_one(),
            1,
        )

    def test_worker_unavailable_uses_dispatcher_eta_and_audits_released_assignment(self):
        ticket_id = self._ticket(title="Заявка перед возвращением инженера")["id"]
        self._assign(ticket_id)
        response = self.client.post(
            f"/api/v1/workers/{self.worker.id}/unavailable",
            json={
                "expected_revision": 1,
                "service_area_id": self.service_area_id,
                "route_date": self.route_date.isoformat(),
                "occurred_at": "2030-01-15T15:00:00+03:00",
                "expected_available_at": "2030-01-15T16:00:00+03:00",
                "worker_id": self.worker.id,
                "reason": "Инженер вернётся после короткой недоступности",
                "payload": {},
            },
            headers=self._auth(self.observer) | {"Idempotency-Key": "worker-unavailable-eta"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            datetime.fromisoformat(response.json()["expected_available_at"]).astimezone(UTC),
            datetime(2030, 1, 15, 13, tzinfo=UTC),
        )
        ticket_state = self.session.execute(
            text(
                "SELECT lifecycle_state, assigned_worker_id, planned_start_at, planned_end_at "
                "FROM tickets WHERE id=:ticket_id"
            ),
            {"ticket_id": ticket_id},
        ).one()
        self.assertEqual(ticket_state, ("waiting_assignment", None, None, None))
        event_types = (
            self.session.execute(
                text("SELECT event_type FROM work_events WHERE ticket_id=:ticket_id ORDER BY id"),
                {"ticket_id": ticket_id},
            )
            .scalars()
            .all()
        )
        self.assertEqual(event_types, ["new_ticket", "assign", "unassign"])

    def test_completion_consumes_material_once_and_reopen_preserves_ledger(self):
        appliance = self._save(
            Appliance(name="Кабель execution", type=ApplianceType.CABLE, unit="м")
        )
        self._save(ApplianceStock(office_id=self.office.id, appliance_id=appliance.id, stock=1))
        ticket_id = self._ticket(title="Заявка с материалом")["id"]
        self._save(
            TicketAppliance(
                ticket_id=ticket_id,
                appliance_id=appliance.id,
                office_id=self.office.id,
                quantity=1,
            )
        )
        self._assign(ticket_id)
        self._progress_to_work(ticket_id)
        complete = self._command(
            f"/api/v1/tickets/{ticket_id}/complete",
            5,
            "equipment-complete",
            "2030-01-15T15:00:00+03:00",
            worker=True,
            location_id=self.destination_location_id,
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        self.session.expire_all()
        stock = self.session.get(
            ApplianceStock, {"office_id": self.office.id, "appliance_id": appliance.id}
        )
        self.assertEqual(stock.stock, 0)
        movement_count = self.session.execute(
            text("SELECT count(*) FROM equipment_movements WHERE ticket_id=:ticket_id"),
            {"ticket_id": ticket_id},
        ).scalar_one()
        self.assertEqual(movement_count, 1)
        self.assertEqual(
            self._command(
                f"/api/v1/tickets/{ticket_id}/complete",
                5,
                "equipment-complete",
                "2030-01-15T15:00:00+03:00",
                worker=True,
                location_id=self.destination_location_id,
            ).status_code,
            200,
        )
        reopened = self._command(
            f"/api/v1/tickets/{ticket_id}/reopen",
            6,
            "equipment-reopen",
            "2030-01-15T16:00:00+03:00",
            reason="Повторная заявка",
        )
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertEqual(
            self.session.execute(
                text("SELECT count(*) FROM equipment_movements WHERE ticket_id=:ticket_id"),
                {"ticket_id": ticket_id},
            ).scalar_one(),
            1,
        )
