"""Integration tests for appliances, warehouse stock, and ticket allocations."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.tickets.enums import TicketStatus
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate, WorkerProfileCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class AppliancesApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        self.observer = self.create_user("appliance_observer", UserRole.OBSERVER)
        self.foreman = self.create_user("appliance_foreman", UserRole.FOREMAN)
        self.worker = self.create_user("appliance_worker", UserRole.WORKER)

        # Create geographical hierarchy
        city_id = self.connection.execute(
            text("INSERT INTO cities (name) VALUES ('Тест Город') RETURNING id")
        ).scalar_one()
        street_id = self.connection.execute(
            text("INSERT INTO streets (name, city_id) VALUES ('Тест Улица', :c_id) RETURNING id"),
            {"c_id": city_id},
        ).scalar_one()
        district_id = self.connection.execute(
            text("INSERT INTO districts (name, city_id) VALUES ('Тест Район', :c_id) RETURNING id"),
            {"c_id": city_id},
        ).scalar_one()
        building_id = self.connection.execute(
            text(
                "INSERT INTO buildings (city_id, street_id, district_id, number) "
                "VALUES (:c, :s, :d, '10') RETURNING id"
            ),
            {"c": city_id, "s": street_id, "d": district_id},
        ).scalar_one()
        self.location_id = self.connection.execute(
            text("INSERT INTO locations (building_id) VALUES (:b) RETURNING id"),
            {"b": building_id},
        ).scalar_one()

        # Create office
        self.office_id = self.connection.execute(
            text(
                "INSERT INTO offices (name, location_id) "
                "VALUES ('Главный Склад', :loc_id) RETURNING id"
            ),
            {"loc_id": self.location_id},
        ).scalar_one()

        # Create brigade and assign worker
        self.brigade_id = self.connection.execute(
            text("""
                INSERT INTO brigades (name, foreman_id, office_id)
                VALUES ('Бригада 1', :f_id, :off_id) RETURNING id
            """),
            {"f_id": self.foreman.id, "off_id": self.office_id},
        ).scalar_one()
        self.connection.execute(
            text("INSERT INTO brigade_members (brigade_id, worker_id) VALUES (:b_id, :w_id)"),
            {"b_id": self.brigade_id, "w_id": self.worker.id},
        )

        # Create sample ticket
        self.ticket_id = self.connection.execute(
            text("""
                INSERT INTO tickets (
                    location_id, title, work_type, status,
                    visit_window_start, visit_window_end, estimated_duration_minutes
                ) VALUES (
                    :loc_id, 'Монтаж роутера', 'Подключение', 'planned',
                    NOW(), NOW() + INTERVAL '2 hours', 60
                ) RETURNING id
            """),
            {"loc_id": self.location_id},
        ).scalar_one()

        # Assign worker to ticket
        self.connection.execute(
            text("INSERT INTO ticket_assignments (ticket_id, worker_id) VALUES (:t_id, :w_id)"),
            {"t_id": self.ticket_id, "w_id": self.worker.id},
        )

        self.session.commit()

    def create_user(self, username: str, role: UserRole):
        worker_profile = None
        if role == UserRole.WORKER:
            worker_profile = WorkerProfileCreate(
                workshift_start="09:00:00",
                workshift_end="18:00:00",
                skills=["Монтаж"],
            )
        user_in = UserCreate(
            name=f"Имя {username}",
            surname=f"Фамилия {username}",
            username=username,
            password="Password123!",
            role=role,
            worker_profile=worker_profile,
        )
        return create_user(self.session, user_in)

    def _auth_headers(self, user) -> dict:
        response = self.client.post(
            "/api/v1/auth/login", json={"username": user.username, "password": "Password123!"}
        )
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_create_appliance_observer(self):
        headers = self._auth_headers(self.observer)
        payload = {
            "name": "Wi-Fi Роутер D-Link DIR-842",
            "description": "Роутер 802.11ac",
            "type": "CLIENT_ROUTER",
            "unit": "шт",
        }
        response = self.client.post("/api/v1/appliances/", json=payload, headers=headers)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], payload["name"])
        self.assertEqual(data["type"], "CLIENT_ROUTER")
        self.assertEqual(data["unit"], "шт")
        self.assertTrue(data["is_active"])

    def test_create_appliance_worker_forbidden(self):
        headers = self._auth_headers(self.worker)
        payload = {
            "name": "Wi-Fi Роутер Zyxel",
            "description": "Роутер",
            "type": "CLIENT_ROUTER",
            "unit": "шт",
        }
        response = self.client.post("/api/v1/appliances/", json=payload, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_create_appliance_duplicate_name_conflict(self):
        headers = self._auth_headers(self.observer)
        payload = {
            "name": "Кабель витая пара",
            "type": "CABLE",
            "unit": "м",
        }
        res1 = self.client.post("/api/v1/appliances/", json=payload, headers=headers)
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post("/api/v1/appliances/", json=payload, headers=headers)
        self.assertEqual(res2.status_code, 409)

    def test_reactivate_archived_appliance_on_create(self):
        headers = self._auth_headers(self.observer)
        payload = {
            "name": "Роутер для архивации",
            "description": "Первоначальное описание",
            "type": "CLIENT_ROUTER",
            "unit": "шт",
        }
        res = self.client.post("/api/v1/appliances/", json=payload, headers=headers)
        self.assertEqual(res.status_code, 201)
        app_id = res.json()["id"]

        # Soft-delete / archive
        del_res = self.client.delete(f"/api/v1/appliances/{app_id}", headers=headers)
        self.assertEqual(del_res.status_code, 204)

        # Verify is_active is False
        get_res = self.client.get(f"/api/v1/appliances/{app_id}", headers=headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertFalse(get_res.json()["is_active"])

        # Re-create with the same name and updated description/unit
        new_payload = {
            "name": "Роутер для архивации",
            "description": "Новое описание после возврата в эксплуатацию",
            "type": "CLIENT_ROUTER",
            "unit": "комплект",
        }
        recreate_res = self.client.post("/api/v1/appliances/", json=new_payload, headers=headers)
        self.assertEqual(recreate_res.status_code, 201)
        data = recreate_res.json()
        self.assertEqual(data["id"], app_id)
        self.assertTrue(data["is_active"])
        self.assertEqual(data["description"], "Новое описание после возврата в эксплуатацию")
        self.assertEqual(data["unit"], "комплект")

    def test_list_and_filter_appliances(self):
        headers = self._auth_headers(self.observer)
        self.client.post(
            "/api/v1/appliances/",
            json={"name": "Кабель UTP 5e", "type": "CABLE", "unit": "м"},
            headers=headers,
        )
        self.client.post(
            "/api/v1/appliances/",
            json={"name": "Оптический патчкорд", "type": "FIBER", "unit": "шт"},
            headers=headers,
        )
        self.client.post(
            "/api/v1/appliances/",
            json={"name": "Роутер Beeline", "type": "CLIENT_ROUTER", "unit": "шт"},
            headers=headers,
        )

        # Filter by type
        res = self.client.get("/api/v1/appliances/?type=CABLE", headers=headers)
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Кабель UTP 5e")

        # Search by name
        res_search = self.client.get("/api/v1/appliances/?search=патчкорд", headers=headers)
        self.assertEqual(res_search.status_code, 200)
        search_items = res_search.json()
        self.assertEqual(len(search_items), 1)
        self.assertEqual(search_items[0]["name"], "Оптический патчкорд")

    def test_office_stock_management(self):
        headers = self._auth_headers(self.observer)

        # Create appliance
        app_res = self.client.post(
            "/api/v1/appliances/",
            json={"name": "Роутер тест склад", "type": "CLIENT_ROUTER", "unit": "шт"},
            headers=headers,
        )
        app_id = app_res.json()["id"]

        # View stock before setting
        stock_list = self.client.get(f"/api/v1/offices/{self.office_id}/stock", headers=headers)
        self.assertEqual(stock_list.status_code, 200)
        item = next(x for x in stock_list.json() if x["appliance_id"] == app_id)
        self.assertEqual(item["stock"], 0)
        self.assertEqual(item["reserved"], 0)
        self.assertEqual(item["available"], 0)

        # Set physical stock to 50
        put_res = self.client.put(
            f"/api/v1/offices/{self.office_id}/stock/{app_id}",
            json={"stock": 50},
            headers=headers,
        )
        self.assertEqual(put_res.status_code, 200)
        updated = put_res.json()
        self.assertEqual(updated["stock"], 50)
        self.assertEqual(updated["reserved"], 0)
        self.assertEqual(updated["available"], 50)

    def test_ticket_appliance_allocation_lifecycle(self):
        headers = self._auth_headers(self.observer)

        # 1. Create router
        app_res = self.client.post(
            "/api/v1/appliances/",
            json={"name": "Роутер распределение", "type": "CLIENT_ROUTER", "unit": "шт"},
            headers=headers,
        )
        app_id = app_res.json()["id"]

        # 2. Set stock to 10 in office
        self.client.put(
            f"/api/v1/offices/{self.office_id}/stock/{app_id}",
            json={"stock": 10},
            headers=headers,
        )

        # 3. Add 4 routers to ticket
        attach_res = self.client.post(
            f"/api/v1/tickets/{self.ticket_id}/appliances",
            json={"appliance_id": app_id, "quantity": 4, "office_id": self.office_id},
            headers=headers,
        )
        self.assertEqual(attach_res.status_code, 201)
        attached_data = attach_res.json()
        self.assertEqual(attached_data["quantity"], 4)

        # 4. Check office stock: stock=10, reserved=4, available=6
        stocks = self.client.get(f"/api/v1/offices/{self.office_id}/stock", headers=headers).json()
        st = next(x for x in stocks if x["appliance_id"] == app_id)
        self.assertEqual(st["stock"], 10)
        self.assertEqual(st["reserved"], 4)
        self.assertEqual(st["available"], 6)

        # 5. Attempt to add more than available (available=6, requesting 7) -> 400
        over_req = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/appliances/{app_id}",
            json={"quantity": 11},  # requires 11 - 4 = 7 more, but available is 6
            headers=headers,
        )
        self.assertEqual(over_req.status_code, 400)

        # 6. Attempt to reduce physical stock below current reserve (reserve=4, setting to 3) -> 400
        reduce_below_res = self.client.put(
            f"/api/v1/offices/{self.office_id}/stock/{app_id}",
            json={"stock": 3},
            headers=headers,
        )
        self.assertEqual(reduce_below_res.status_code, 400)

        # 7. Update quantity to 6
        update_res = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/appliances/{app_id}",
            json={"quantity": 6},
            headers=headers,
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["quantity"], 6)

        # 8. Verify ticket appliances list
        list_res = self.client.get(f"/api/v1/tickets/{self.ticket_id}/appliances", headers=headers)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.json()), 1)
        self.assertEqual(list_res.json()[0]["quantity"], 6)

        # 9. Delete appliance from ticket
        del_res = self.client.delete(
            f"/api/v1/tickets/{self.ticket_id}/appliances/{app_id}",
            headers=headers,
        )
        self.assertEqual(del_res.status_code, 204)

        # 10. Check that stock is fully available again (reserved=0, available=10)
        res_after = self.client.get(f"/api/v1/offices/{self.office_id}/stock", headers=headers)
        stocks_after = res_after.json()
        st_after = next(x for x in stocks_after if x["appliance_id"] == app_id)
        self.assertEqual(st_after["reserved"], 0)
        self.assertEqual(st_after["available"], 10)

    def test_consumables_deduction_on_ticket_completed(self):
        headers = self._auth_headers(self.observer)

        # Create consumable router and durable tool
        router = self.client.post(
            "/api/v1/appliances/",
            json={"name": "Списываемый роутер", "type": "CLIENT_ROUTER", "unit": "шт"},
            headers=headers,
        ).json()
        tool = self.client.post(
            "/api/v1/appliances/",
            json={"name": "Несписываемый инструмент", "type": "TOOL", "unit": "шт"},
            headers=headers,
        ).json()

        # Set initial stocks: 20 routers, 5 tools
        self.client.put(
            f"/api/v1/offices/{self.office_id}/stock/{router['id']}",
            json={"stock": 20},
            headers=headers,
        )
        self.client.put(
            f"/api/v1/offices/{self.office_id}/stock/{tool['id']}",
            json={"stock": 5},
            headers=headers,
        )

        # Assign 2 routers and 1 tool to ticket
        self.client.post(
            f"/api/v1/tickets/{self.ticket_id}/appliances",
            json={"appliance_id": router["id"], "quantity": 2, "office_id": self.office_id},
            headers=headers,
        )
        self.client.post(
            f"/api/v1/tickets/{self.ticket_id}/appliances",
            json={"appliance_id": tool["id"], "quantity": 1, "office_id": self.office_id},
            headers=headers,
        )

        # Complete ticket
        status_res = self.client.patch(
            f"/api/v1/tickets/{self.ticket_id}/status",
            json={"status": TicketStatus.COMPLETED.value},
            headers=headers,
        )
        self.assertEqual(status_res.status_code, 200)

        # Verify office stocks:
        # Router: physical stock was 20, consumed 2 -> stock=18, reserved=0, available=18
        # Tool: physical stock was 5, NOT consumed (retained) -> stock=5, reserved=0, available=5
        stocks = self.client.get(f"/api/v1/offices/{self.office_id}/stock", headers=headers).json()
        router_st = next(x for x in stocks if x["appliance_id"] == router["id"])
        tool_st = next(x for x in stocks if x["appliance_id"] == tool["id"])

        self.assertEqual(router_st["stock"], 18)
        self.assertEqual(router_st["reserved"], 0)
        self.assertEqual(router_st["available"], 18)

        self.assertEqual(tool_st["stock"], 5)
        self.assertEqual(tool_st["reserved"], 0)
        self.assertEqual(tool_st["available"], 5)
