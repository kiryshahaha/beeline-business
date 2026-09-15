"""Integration tests for users, workers, skills, and JWT auth with refresh tokens."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.main import app
from app.modules.users.enums import UserRole
from app.modules.users.schemas import UserCreate
from app.modules.users.service import create_user
from tests.support import DatabaseTestCase


class UsersAndAuthApiTests(DatabaseTestCase):
    def setUp(self):
        super().setUp()

        def override_session():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = self.enterContext(TestClient(app))

        # Seed an initial observer directly via service
        self.observer = create_user(
            self.session,
            UserCreate(
                name="Администратор",
                surname="Главный",
                lastname="Иванович",
                username="admin_observer",
                password="ObserverPassword123!",
                role=UserRole.OBSERVER,
                worker_profile=None,
            ),
        )
        self.session.commit()

    def get_auth_tokens(self, username: str, password: str) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_login_success_and_invalid_credentials(self):
        # Invalid password
        res = self.client.post(
            "/api/v1/auth/login",
            json={"username": "admin_observer", "password": "WrongPassword!"},
        )
        self.assertEqual(res.status_code, 401)

        # Valid credentials
        tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        self.assertIn("access_token", tokens)
        self.assertIn("refresh_token", tokens)
        self.assertEqual(tokens["token_type"], "bearer")

    def test_user_me_endpoint(self):
        # Unauthenticated
        res = self.client.get("/api/v1/users/me")
        self.assertEqual(res.status_code, 401)

        # Authenticated observer
        tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        res = self.client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["username"], "admin_observer")
        self.assertEqual(data["role"], "observer")
        self.assertIsNone(data["worker_profile"])

    def test_skills_crud_and_role_permissions(self):
        tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Create skill as observer
        res = self.client.post(
            "/api/v1/worker/skills",
            json={"skill": "Монтаж ВОЛС"},
            headers=auth_header,
        )
        self.assertEqual(res.status_code, 201)
        skill_id = res.json()["id"]
        self.assertEqual(res.json()["skill"], "Монтаж ВОЛС")
        self.assertEqual(res.headers["Location"], f"/api/v1/worker/skills/{skill_id}")

        # Duplicate skill returns 409
        res = self.client.post(
            "/api/v1/worker/skills",
            json={"skill": "монтаж волс"},
            headers=auth_header,
        )
        self.assertEqual(res.status_code, 409)

        # List skills
        res = self.client.get("/api/v1/worker/skills", headers=auth_header)
        self.assertEqual(res.status_code, 200)
        skills = res.json()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["skill"], "Монтаж ВОЛС")

    def test_create_worker_with_night_shift_and_skills(self):
        observer_tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        auth_header = {"Authorization": f"Bearer {observer_tokens['access_token']}"}

        worker_payload = {
            "name": "Сергей",
            "surname": "Васильев",
            "lastname": None,
            "username": "vasiliev_worker",
            "password": "WorkerPass1234!",
            "role": "worker",
            "worker_profile": {
                "workshift_start": "22:00:00",
                "workshift_end": "06:00:00",
                "skills": ["Настройка роутеров", "Ремонт кабеля"],
            },
        }

        res = self.client.post("/api/v1/users", json=worker_payload, headers=auth_header)
        self.assertEqual(res.status_code, 201)
        created_worker = res.json()
        self.assertEqual(created_worker["username"], "vasiliev_worker")
        self.assertEqual(created_worker["role"], "worker")
        self.assertIsNone(created_worker["lastname"])
        self.assertIsNotNone(created_worker["worker_profile"])
        self.assertEqual(created_worker["worker_profile"]["workshift_start"], "22:00:00")
        self.assertEqual(created_worker["worker_profile"]["workshift_end"], "06:00:00")
        self.assertCountEqual(
            created_worker["worker_profile"]["skills"],
            ["Настройка роутеров", "Ремонт кабеля"],
        )

        # Worker can log in and see their profile
        worker_tokens = self.get_auth_tokens("vasiliev_worker", "WorkerPass1234!")
        worker_header = {"Authorization": f"Bearer {worker_tokens['access_token']}"}
        me_res = self.client.get("/api/v1/users/me", headers=worker_header)
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(
            me_res.json()["worker_profile"]["skills"],
            ["Настройка роутеров", "Ремонт кабеля"],
        )

        # Worker cannot create users (only observer can)
        res_forbidden = self.client.post(
            "/api/v1/users",
            json={
                "name": "Тест",
                "surname": "Тестов",
                "username": "test_user2",
                "password": "Password123!",
                "role": "observer",
            },
            headers=worker_header,
        )
        self.assertEqual(res_forbidden.status_code, 403)

        # Worker cannot create skills (only observer can)
        res_skill_forbidden = self.client.post(
            "/api/v1/worker/skills",
            json={"skill": "Новый навык"},
            headers=worker_header,
        )
        self.assertEqual(res_skill_forbidden.status_code, 403)

        # Both observer and worker can list all users
        res_list = self.client.get("/api/v1/users", headers=worker_header)
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()), 2)

    def test_refresh_token_rotation_and_logout(self):
        tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        old_refresh = tokens["refresh_token"]

        # Refresh to get new token pair
        refresh_res = self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        self.assertEqual(refresh_res.status_code, 200)
        new_tokens = refresh_res.json()
        new_refresh = new_tokens["refresh_token"]
        self.assertNotEqual(old_refresh, new_refresh)

        # Old refresh token is revoked
        res_old = self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        self.assertEqual(res_old.status_code, 401)

        # Logout with current refresh token
        logout_res = self.client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": new_refresh},
        )
        self.assertEqual(logout_res.status_code, 200)

        # Attempting refresh after logout fails
        res_after_logout = self.client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        self.assertEqual(res_after_logout.status_code, 401)

    def test_update_user_by_observer(self):
        observer_tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        auth_header = {"Authorization": f"Bearer {observer_tokens['access_token']}"}

        # Create worker
        create_res = self.client.post(
            "/api/v1/users",
            json={
                "name": "Игорь",
                "surname": "Семенов",
                "username": "semenov_worker",
                "password": "InitialPassword123!",
                "role": "worker",
                "worker_profile": {
                    "workshift_start": "09:00:00",
                    "workshift_end": "18:00:00",
                    "skills": ["Навык 1"],
                },
            },
            headers=auth_header,
        )
        self.assertEqual(create_res.status_code, 201)
        user_id = create_res.json()["id"]

        # Worker cannot update user
        worker_tokens = self.get_auth_tokens("semenov_worker", "InitialPassword123!")
        worker_header = {"Authorization": f"Bearer {worker_tokens['access_token']}"}
        res_forbidden = self.client.patch(
            f"/api/v1/users/{user_id}",
            json={"name": "НовоеИмя"},
            headers=worker_header,
        )
        self.assertEqual(res_forbidden.status_code, 403)

        # Observer updates user's name, shift, and skills
        patch_res = self.client.patch(
            f"/api/v1/users/{user_id}",
            json={
                "name": "ИгорьОбновленный",
                "worker_profile": {
                    "workshift_start": "10:00:00",
                    "workshift_end": "19:00:00",
                    "skills": ["Навык 1", "Новый навык 2"],
                },
            },
            headers=auth_header,
        )
        self.assertEqual(patch_res.status_code, 200)
        updated = patch_res.json()
        self.assertEqual(updated["name"], "ИгорьОбновленный")
        self.assertEqual(updated["worker_profile"]["workshift_start"], "10:00:00")
        self.assertCountEqual(updated["worker_profile"]["skills"], ["Навык 1", "Новый навык 2"])

        # Observer updating to existing username returns 409
        res_conflict = self.client.patch(
            f"/api/v1/users/{user_id}",
            json={"username": "admin_observer"},
            headers=auth_header,
        )
        self.assertEqual(res_conflict.status_code, 409)

    def test_delete_user_by_observer(self):
        observer_tokens = self.get_auth_tokens("admin_observer", "ObserverPassword123!")
        auth_header = {"Authorization": f"Bearer {observer_tokens['access_token']}"}

        # Create worker to delete
        create_res = self.client.post(
            "/api/v1/users",
            json={
                "name": "Удаляемый",
                "surname": "Пользователь",
                "username": "to_be_deleted",
                "password": "Password12345!",
                "role": "worker",
                "worker_profile": {
                    "workshift_start": "08:00:00",
                    "workshift_end": "16:00:00",
                    "skills": ["Навык Удаления"],
                },
            },
            headers=auth_header,
        )
        self.assertEqual(create_res.status_code, 201)
        user_id = create_res.json()["id"]

        # Worker cannot delete users
        worker_tokens = self.get_auth_tokens("to_be_deleted", "Password12345!")
        worker_header = {"Authorization": f"Bearer {worker_tokens['access_token']}"}
        res_forbidden = self.client.delete(
            f"/api/v1/users/{user_id}",
            headers=worker_header,
        )
        self.assertEqual(res_forbidden.status_code, 403)

        # Observer cannot delete self
        res_self = self.client.delete(
            f"/api/v1/users/{self.observer.id}",
            headers=auth_header,
        )
        self.assertEqual(res_self.status_code, 400)

        # Observer successfully deletes user
        delete_res = self.client.delete(
            f"/api/v1/users/{user_id}",
            headers=auth_header,
        )
        self.assertEqual(delete_res.status_code, 204)

        # User is gone
        get_res = self.client.get(f"/api/v1/users/{user_id}", headers=auth_header)
        self.assertEqual(get_res.status_code, 404)

        # Deleting non-existent returns 404
        delete_again = self.client.delete(
            f"/api/v1/users/{user_id}",
            headers=auth_header,
        )
        self.assertEqual(delete_again.status_code, 404)
