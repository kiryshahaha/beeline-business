"""HTTP contracts exercised against migrated PostgreSQL, with a fresh session per request."""

from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Building, City, District, Entrance, Location, Street, Ticket
from app.db.session import get_session
from app.main import app
from app.modules.tickets import repository
from app.modules.tickets.enums import TicketStatus
from tests.support import DatabaseTestCase


class TicketsApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        city = self.save(City(name="Санкт-Петербург"))
        self.city_id = city.id
        district = self.save(District(city_id=city.id, name="Невский район"))
        self.district_id = district.id
        street = self.save(Street(city_id=city.id, name="Тестовая улица"))
        building = self.save(
            Building(
                city_id=city.id,
                street_id=street.id,
                district_id=district.id,
                number="12А",
                block="корпус 2",
            )
        )
        entrance = self.save(Entrance(building_id=building.id, number="3"))
        self.location = self.save(
            Location(
                building_id=building.id,
                entrance_id=entrance.id,
                apartment="24Б",
                floor=5,
                latitude=59.94,
                longitude=30.32,
            )
        )
        self.location_id = self.location.id
        # Release the fixture savepoint; HTTP sessions share only the outer test transaction.
        self.session.commit()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

    def save(self, instance):
        self.session.add(instance)
        self.session.flush()
        return instance

    def payload(self, **overrides):
        return {
            "location_id": self.location_id,
            "title": "Настроить Wi-Fi",
            "work_type": "Настройка сети",
            "visit_window_start": "2026-09-14T10:00:00+03:00",
            "visit_window_end": "2026-09-14T14:00:00+03:00",
            "estimated_duration_minutes": 60,
        } | overrides

    def create(self, **overrides):
        return self.client.post("/api/v1/tickets", json=self.payload(**overrides))

    def count_tickets(self):
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            return session.scalar(select(func.count()).select_from(Ticket))

    def test_post_then_get_with_fresh_session_returns_persisted_ticket_and_address(self):
        response = self.create(title="  Настроить Wi-Fi  ")
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()
        self.assertEqual(created["title"], "Настроить Wi-Fi")
        self.assertEqual(created["status"], "planned")
        self.assertIsNone(created["planned_start_at"])
        self.assertIsNone(created["actual_duration_minutes"])
        self.assertIsNotNone(datetime.fromisoformat(created["created_at"]).tzinfo)
        self.assertIsNotNone(datetime.fromisoformat(created["updated_at"]).tzinfo)
        self.assertEqual(created["location_id"], self.location_id)
        location = created["location"]
        self.assertEqual(location["id"], self.location_id)
        self.assertEqual(location["district_id"], self.district_id)
        self.assertEqual(location["district"], "Невский район")
        self.assertEqual(location["apartment"], "24Б")
        self.assertEqual(location["latitude"], 59.94)
        self.assertEqual(location["longitude"], 30.32)
        self.assertEqual(
            location["address"],
            "Санкт-Петербург, Невский район, Тестовая улица, д. 12А, корпус 2, "
            "подъезд 3, этаж 5, кв./пом. 24Б",
        )
        fetched = self.client.get(response.headers["Location"])
        self.assertEqual(fetched.status_code, 200)
        read_back = fetched.json()
        for field in ("visit_window_start", "visit_window_end", "created_at", "updated_at"):
            self.assertEqual(
                datetime.fromisoformat(read_back.pop(field)),
                datetime.fromisoformat(created.pop(field)),
            )
        self.assertEqual(read_back, created)
        self.assertEqual(self.count_tickets(), 1)

    def test_manual_duration_and_planned_interval_are_independent(self):
        response = self.create(
            planned_start_at="2026-09-14T11:00:00+03:00",
            planned_end_at="2026-09-14T12:00:00+03:00",
            actual_duration_minutes=75,
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["actual_duration_minutes"], 75)
        response = self.create(actual_duration_minutes=0)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["actual_duration_minutes"], 0)

    def test_get_reflects_district_changed_in_address_directory(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        building = self.session.get(Building, self.location.building_id)
        district = self.save(District(city_id=building.city_id, name="Тестовый район"))
        building.district_id = district.id
        district_id = district.id
        self.session.commit()
        fetched = self.client.get(response.headers["Location"])
        self.assertEqual(fetched.status_code, 200, fetched.text)
        location = fetched.json()["location"]
        self.assertEqual(location["district_id"], district_id)
        self.assertEqual(location["district"], "Тестовый район")
        self.assertEqual(
            location["address"],
            "Санкт-Петербург, Тестовый район, Тестовая улица, д. 12А, корпус 2, "
            "подъезд 3, этаж 5, кв./пом. 24Б",
        )

    def test_sql_like_text_is_returned_unchanged(self):
        values = {
            "title": "Офис 'Север'; SELECT 1 --",
            "work_type": "Wi-Fi 'настройка'",
            "description": "Кавычки: ' и \"; параметры :ticket_id и % остаются текстом.",
        }
        response = self.create(**values)
        self.assertEqual(response.status_code, 201, response.text)
        fetched = self.client.get(response.headers["Location"])
        self.assertEqual(fetched.status_code, 200)
        for field, value in values.items():
            self.assertEqual(fetched.json()[field], value)
        self.assertEqual(self.count_tickets(), 1)

    def test_failure_after_insert_rolls_back_ticket(self):
        with patch(
            "app.modules.tickets.service.get_ticket", side_effect=RuntimeError("response failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "response failed"):
                self.create()
        self.assertEqual(self.count_tickets(), 0)

    def test_all_agreed_statuses_are_accepted(self):
        for status in TicketStatus:
            with self.subTest(status=status):
                response = self.create(status=status.value)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["status"], status.value)

    def test_maximum_text_lengths_and_durations_are_saved_without_truncation(self):
        values = {
            "title": "Я" * 200,
            "work_type": "Ю" * 100,
            "estimated_duration_minutes": 2_147_483_647,
            "actual_duration_minutes": 2_147_483_647,
        }
        response = self.create(**values)
        self.assertEqual(response.status_code, 201, response.text)
        fetched = self.client.get(response.headers["Location"])
        self.assertEqual(fetched.status_code, 200, fetched.text)
        for field, value in values.items():
            self.assertEqual(fetched.json()[field], value)

    def test_zero_floor_and_coordinates_are_kept_in_the_address_response(self):
        self.location.floor = 0
        self.location.latitude = 0
        self.location.longitude = 0
        self.session.commit()
        response = self.create(work_type="  Настройка Wi-Fi  ")
        self.assertEqual(response.status_code, 201, response.text)
        fetched = self.client.get(response.headers["Location"])
        self.assertEqual(fetched.status_code, 200, fetched.text)
        data = fetched.json()
        self.assertEqual(data["work_type"], "Настройка Wi-Fi")
        self.assertEqual(data["location"]["floor"], 0)
        self.assertEqual(data["location"]["latitude"], 0)
        self.assertEqual(data["location"]["longitude"], 0)
        self.assertIn("этаж 0", data["location"]["address"])

    def test_openapi_examples_keep_null_fields_and_create_a_valid_ticket(self):
        schemas = self.client.get("/openapi.json").json()["components"]["schemas"]
        for schema in ("TicketCreate", "TicketRead"):
            example = schemas[schema]["examples"][0]
            for field in ("planned_start_at", "planned_end_at", "actual_duration_minutes"):
                self.assertIn(field, example)
                self.assertIsNone(example[field])
        payload = schemas["TicketCreate"]["examples"][0] | {"location_id": self.location_id}
        response = self.client.post("/api/v1/tickets", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["title"], payload["title"])
        self.assertIsNone(response.json()["actual_duration_minutes"])

    def test_timezones_are_compared_as_instants(self):
        response = self.create(visit_window_end="2026-09-14T08:00:00Z")
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        delta = datetime.fromisoformat(data["visit_window_end"]) - datetime.fromisoformat(
            data["visit_window_start"]
        )
        self.assertEqual(delta, timedelta(hours=1))

    def test_plan_containment_is_not_an_agreed_constraint_yet(self):
        response = self.create(
            planned_start_at="2026-09-14T15:00:00+03:00",
            planned_end_at="2026-09-14T16:00:00+03:00",
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_invalid_inputs_are_422_and_do_not_insert_tickets(self):
        invalid = [
            {"title": " "},
            {"title": "x" * 201},
            {"work_type": ""},
            {"work_type": "x" * 101},
            {"description": "text\x00text"},
            {"title": "text\x00text"},
            {"work_type": "text\x00text"},
            {"status": "unknown"},
            {"location_id": 0},
            {"location_id": -1},
            {"location_id": True},
            {"location_id": "1"},
            {"location_id": 1.5},
            {"location_id": 2**31},
            {"estimated_duration_minutes": 0},
            {"estimated_duration_minutes": 2**31},
            {"estimated_duration_minutes": 1.5},
            {"estimated_duration_minutes": True},
            {"estimated_duration_minutes": "60"},
            {"actual_duration_minutes": -1},
            {"actual_duration_minutes": 2**31},
            {"actual_duration_minutes": False},
            {"actual_duration_minutes": 1.5},
            {"actual_duration_minutes": "60"},
            {"title": None},
            {"status": None},
            {"visit_window_start": "2026-09-14T10:00:00"},
            {"visit_window_end": "2026-09-14T14:00:00"},
            {"visit_window_end": "2026-09-14T10:00:00+03:00"},
            {"visit_window_end": "2026-09-14T06:00:00Z"},
            {"planned_start_at": "2026-09-14T11:00:00+03:00"},
            {"planned_end_at": "2026-09-14T12:00:00+03:00"},
            {
                "planned_start_at": "2026-09-14T11:00:00",
                "planned_end_at": "2026-09-14T12:00:00+03:00",
            },
            {
                "planned_start_at": "2026-09-14T11:00:00+03:00",
                "planned_end_at": "2026-09-14T12:00:00",
            },
            {
                "planned_start_at": "2026-09-14T11:00:00+03:00",
                "planned_end_at": "2026-09-14T08:00:00Z",
            },
            {
                "planned_start_at": "2026-09-14T12:00:00+03:00",
                "planned_end_at": "2026-09-14T11:00:00+03:00",
            },
            {"id": 123},
            {"created_at": "2026-09-14T10:00:00Z"},
            {"unexpected": "value"},
        ]
        for values in invalid:
            with self.subTest(values=values):
                self.assertEqual(self.create(**values).status_code, 422)
        for field in (
            "location_id",
            "title",
            "work_type",
            "visit_window_start",
            "visit_window_end",
            "estimated_duration_minutes",
        ):
            payload = self.payload()
            del payload[field]
            with self.subTest(missing=field):
                self.assertEqual(self.client.post("/api/v1/tickets", json=payload).status_code, 422)
        self.assertEqual(self.count_tickets(), 0)

    def test_unknown_location_does_not_create_ticket(self):
        response = self.create(location_id=2_147_483_647)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "Место выполнения не найдено"})
        self.assertEqual(self.count_tickets(), 0)

    def test_missing_malformed_and_non_object_bodies_do_not_create_tickets(self):
        for body in ("", "{", "null", "[]", '"text"'):
            with self.subTest(body=body):
                response = self.client.post(
                    "/api/v1/tickets", content=body, headers={"Content-Type": "application/json"}
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("detail", response.json())
        self.assertEqual(self.count_tickets(), 0)

    def test_two_requests_at_one_address_remain_independent_tickets(self):
        first = self.create(title="Настроить Wi-Fi", status="completed", actual_duration_minutes=25)
        second = self.create(title="Проверить скорость")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        results = []
        for created in (first, second):
            response = self.client.get(created.headers["Location"])
            self.assertEqual(response.status_code, 200, response.text)
            results.append(response.json())
        self.assertEqual(results[0]["location"], results[1]["location"])
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["actual_duration_minutes"], 25)
        self.assertEqual(results[1]["status"], "planned")
        self.assertIsNone(results[1]["actual_duration_minutes"])
        self.assertEqual(self.count_tickets(), 2)

    def test_missing_ticket_and_invalid_path_id(self):
        response = self.client.get("/api/v1/tickets/2147483647")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Заявка не найдена"})
        for ticket_id in ("0", "-1", "text", "2147483648"):
            with self.subTest(ticket_id=ticket_id):
                self.assertEqual(self.client.get(f"/api/v1/tickets/{ticket_id}").status_code, 422)

    def test_building_location_without_coordinates_and_apartment_can_be_read(self):
        self.session.get(Building, self.location.building_id).block = None
        self.location.entrance_id = None
        self.location.floor = None
        self.location.apartment = None
        self.location.latitude = None
        self.location.longitude = None
        self.session.commit()
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        location = response.json()["location"]
        for field in (
            "block",
            "entrance_id",
            "entrance_number",
            "floor",
            "apartment",
            "latitude",
            "longitude",
        ):
            self.assertIsNone(location[field])
        self.assertEqual(
            location["address"], "Санкт-Петербург, Невский район, Тестовая улица, д. 12А"
        )
        listed = self.client.get("/api/v1/tickets")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), [response.json()])

    def test_list_with_no_tickets_returns_empty_array(self):
        response = self.client.get("/api/v1/tickets")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])

    def test_list_returns_same_full_responses_as_get_by_id(self):
        first = self.create()
        second = self.create(status="completed", actual_duration_minutes=75)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        expected = [
            self.client.get(created.headers["Location"]).json() for created in (first, second)
        ]
        response = self.client.get("/api/v1/tickets")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), expected)

    def test_list_filters_by_ids_and_status_with_and_semantics(self):
        def another_location(city_id, district_name):
            district = self.save(District(city_id=city_id, name=district_name))
            street = self.save(Street(city_id=city_id, name="Другая улица"))
            building = self.save(
                Building(city_id=city_id, street_id=street.id, district_id=district.id, number="1")
            )
            return self.save(Location(building_id=building.id))

        second_location = another_location(self.city_id, "Тестовый район")
        other_city = self.save(City(name="Другой город"))
        # The same district name in another city must not affect filtering by ID.
        other_location = another_location(other_city.id, "Невский район")
        second_location_id, other_location_id = second_location.id, other_location.id
        other_city_id = other_city.id
        self.session.commit()

        status_ids = {}
        for ticket_status in TicketStatus:
            response = self.create(status=ticket_status.value)
            self.assertEqual(response.status_code, 201, response.text)
            status_ids[ticket_status.value] = response.json()["id"]
        second = self.create(location_id=second_location_id)
        other = self.create(location_id=other_location_id, status="in_progress")
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(other.status_code, 201, other.text)
        second_id, other_id = second.json()["id"], other.json()["id"]
        second_district_id = second.json()["location"]["district_id"]
        other_district_id = other.json()["location"]["district_id"]
        cases = [
            ({"city_id": self.city_id}, [*status_ids.values(), second_id]),
            ({"city_id": other_city_id}, [other_id]),
            ({"district_id": self.district_id}, list(status_ids.values())),
            ({"district_id": second_district_id}, [second_id]),
            ({"district_id": other_district_id}, [other_id]),
            ({"status": "planned"}, [status_ids["planned"], second_id]),
            ({"status": "in_progress"}, [status_ids["in_progress"], other_id]),
            ({"status": "completed"}, [status_ids["completed"]]),
            ({"status": "wont_fix"}, [status_ids["wont_fix"]]),
            ({"city_id": self.city_id, "status": "in_progress"}, [status_ids["in_progress"]]),
            (
                {"city_id": self.city_id, "district_id": self.district_id, "status": "planned"},
                [status_ids["planned"]],
            ),
            ({"city_id": other_city_id, "district_id": self.district_id}, []),
            ({"city_id": 2_147_483_647}, []),
            ({"district_id": 2_147_483_647}, []),
            ({"status": "planned", "limit": 1, "offset": 1}, [second_id]),
        ]
        for params, expected_ids in cases:
            with self.subTest(params=params):
                response = self.client.get("/api/v1/tickets", params=params)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([ticket["id"] for ticket in response.json()], expected_ids)

    def test_list_pagination_has_stable_order_and_bounded_default_page(self):
        ids = []
        for index in range(23):
            response = self.create(title=f"Заявка {index}")
            self.assertEqual(response.status_code, 201, response.text)
            ids.append(response.json()["id"])
        cases = [
            ({}, ids[:20]),
            ({"limit": 2, "offset": 1}, ids[1:3]),
            ({"offset": 20}, ids[20:]),
            ({"offset": len(ids)}, []),
            ({"offset": 2_147_483_647}, []),
            ({"limit": 100}, ids),
        ]
        for params, expected_ids in cases:
            with self.subTest(params=params):
                response = self.client.get("/api/v1/tickets", params=params)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([ticket["id"] for ticket in response.json()], expected_ids)

    def test_invalid_list_parameters_return_422(self):
        invalid_values = {
            "status": ["unknown", "", "planned' OR 1=1 --"],
            "city_id": [0, -1, 2_147_483_648, "text", "1.5", ""],
            "district_id": [0, -1, 2_147_483_648, "text", "1.5", ""],
            "limit": [0, -1, 101, "text", "1.5", ""],
            "offset": [-1, 2_147_483_648, "text", "1.5", ""],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.get("/api/v1/tickets", params={field: value})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.json()["detail"][0]["loc"], ["query", field])

    def test_list_status_is_bound_even_without_http_validation(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            filters = {"city_id": None, "district_id": None, "limit": 100, "offset": 0}
            normal = repository.find_tickets(session, status="planned", **filters)
            self.assertEqual([row["id"] for row in normal], [response.json()["id"]])
            # Bypass the HTTP enum check to exercise actual PostgreSQL parameter binding.
            for payload in ("planned' OR 1=1 --", "' OR '1'='1", "planned'; SELECT 1 --"):
                with self.subTest(payload=payload):
                    self.assertEqual(
                        repository.find_tickets(session, status=payload, **filters), []
                    )
        self.assertEqual(self.count_tickets(), 1)

    def test_openapi_exposes_ticket_read_write_and_workflow_operations(self):
        schema = self.client.get("/openapi.json").json()
        paths = schema["paths"]
        ticket_paths = {path for path in paths if path.startswith("/api/v1/tickets")}
        self.assertEqual(
            ticket_paths,
            {
                "/api/v1/tickets",
                "/api/v1/tickets/{id}",
                "/api/v1/tickets/{id}/appliances",
                "/api/v1/tickets/{id}/appliances/{appliance_id}",
                "/api/v1/tickets/{id}/assignees",
                "/api/v1/tickets/{id}/comments",
                "/api/v1/tickets/{id}/comments/{comment_id}",
                "/api/v1/tickets/{id}/equipment/restore",
                "/api/v1/tickets/{id}/status",
            },
        )
        self.assertEqual(set(paths["/api/v1/tickets"]), {"post", "get"})
        self.assertEqual(set(paths["/api/v1/tickets/{id}"]), {"get"})
        self.assertEqual(set(paths["/api/v1/tickets/{id}/assignees"]), {"put"})
        self.assertEqual(set(paths["/api/v1/tickets/{id}/comments"]), {"get", "post"})
        comment_update = paths["/api/v1/tickets/{id}/comments/{comment_id}"]
        self.assertEqual(set(comment_update), {"patch"})
        self.assertIn({"BearerAuth": []}, comment_update["patch"]["security"])
        self.assertEqual(set(paths["/api/v1/tickets/{id}/status"]), {"patch"})
        operation = paths["/api/v1/tickets"]["get"]
        parameters = {param["name"]: param for param in operation["parameters"]}
        self.assertEqual(
            set(parameters), {"status", "city_id", "district_id", "brigade_id", "limit", "offset"}
        )
        self.assertFalse(parameters["brigade_id"]["required"])
        self.assertEqual(parameters["brigade_id"]["schema"]["anyOf"][0]["minimum"], 1)
        self.assertEqual(parameters["brigade_id"]["schema"]["anyOf"][0]["maximum"], 2_147_483_647)
        self.assertTrue(all(param["in"] == "query" for param in parameters.values()))
        self.assertEqual(parameters["limit"]["schema"]["default"], 20)
        self.assertEqual(parameters["offset"]["schema"]["default"], 0)
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["type"], "array"
        )
        location_schema = schema["components"]["schemas"]["LocationRead"]
        for field, field_type in (("district_id", "integer"), ("district", "string")):
            self.assertIn(field, location_schema["required"])
            self.assertEqual(location_schema["properties"][field]["type"], field_type)
            self.assertNotIn("anyOf", location_schema["properties"][field])
