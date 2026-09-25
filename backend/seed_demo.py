"""Fill an existing, migrated database: python seed_demo.py [--date YYYY-MM-DD]."""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_engine

MOSCOW_TIME = timezone(timedelta(hours=3))
CITY_NAME = "Санкт-Петербург"


@dataclass(frozen=True, kw_only=True)
class DemoVisit:
    district: str
    street: str
    building: str
    latitude: str
    longitude: str
    source_url: str
    title: str
    work_type: str
    start_hour: int
    end_hour: int
    duration_minutes: int
    block: str | None = None
    entrance: str | None = None
    floor: int | None = None
    apartment: str | None = None

    @property
    def address(self) -> str:
        parts = [CITY_NAME, self.district, self.street, f"д. {self.building}"]
        if self.block is not None:
            parts.append(self.block)
        if self.entrance is not None:
            parts.append(f"подъезд {self.entrance}")
        if self.floor is not None:
            parts.append(f"этаж {self.floor}")
        if self.apartment is not None:
            parts.append(f"кв./пом. {self.apartment}")
        return ", ".join(parts)


# Buildings, districts, blocks and map coordinates checked on 2026-09-13.
# Entrance/floor/apartment assignments and all jobs are fictional by user agreement.
# Repeated apartments share the building's map point, not a surveyed entrance position.
DEMO_VISITS = (
    DemoVisit(
        district="Невский район",
        street="Искровский проспект",
        building="4",
        block="корпус 2",
        latitude="59.9156",
        longitude="30.4631",
        source_url="https://spb.ginfo.ru/ulicy/iskrovskiy_prospekt/4k2/info/",
        entrance="1",
        floor=3,
        apartment="12",
        title="[Демо] Настроить Wi-Fi",
        work_type="Настройка сети",
        start_hour=9,
        end_hour=13,
        duration_minutes=60,
    ),
    DemoVisit(
        district="Невский район",
        street="Искровский проспект",
        building="4",
        block="корпус 2",
        latitude="59.9156",
        longitude="30.4631",
        source_url="https://spb.ginfo.ru/ulicy/iskrovskiy_prospekt/4k2/info/",
        entrance="1",
        floor=4,
        apartment="16",
        title="[Демо] Подключить соседнюю квартиру",
        work_type="Настройка сети",
        start_hour=10,
        end_hour=14,
        duration_minutes=45,
    ),
    DemoVisit(
        district="Невский район",
        street="Искровский проспект",
        building="4",
        block="корпус 2",
        latitude="59.9156",
        longitude="30.4631",
        source_url="https://spb.ginfo.ru/ulicy/iskrovskiy_prospekt/4k2/info/",
        entrance="1",
        floor=3,
        apartment="12",
        title="[Демо] Повторно проверить соединение",
        work_type="Диагностика сети",
        start_hour=14,
        end_hour=18,
        duration_minutes=30,
    ),
    DemoVisit(
        district="Невский район",
        street="Искровский проспект",
        building="3",
        block="корпус 2",
        latitude="59.9127",
        longitude="30.458",
        source_url="https://spb.ginfo.ru/ulicy/iskrovskiy_prospekt/3k2/info/",
        entrance="2",
        floor=5,
        apartment="56",
        title="[Демо] Заменить маршрутизатор",
        work_type="Замена оборудования",
        start_hour=11,
        end_hour=16,
        duration_minutes=60,
    ),
    DemoVisit(
        district="Невский район",
        street="улица Дыбенко",
        building="8",
        block="корпус 2",
        latitude="59.9015",
        longitude="30.4548",
        source_url="https://spb.ginfo.ru/ulicy/ulica_dybenko/8k2/info/",
        entrance="1",
        floor=2,
        apartment="7",
        title="[Демо] Проверить кабель",
        work_type="Диагностика сети",
        start_hour=9,
        end_hour=12,
        duration_minutes=30,
    ),
    DemoVisit(
        district="Невский район",
        street="улица Дыбенко",
        building="27",
        block="корпус 1",
        latitude="59.9056",
        longitude="30.4799",
        source_url="https://spb.ginfo.ru/ulicy/ulica_dybenko/27k1/info/",
        entrance="2",
        floor=3,
        apartment="48",
        title="[Демо] Подключить точку доступа",
        work_type="Настройка сети",
        start_hour=13,
        end_hour=18,
        duration_minutes=90,
    ),
    DemoVisit(
        district="Приморский район",
        street="Коломяжский проспект",
        building="34",
        block="корпус 2",
        latitude="60.0137",
        longitude="30.2931",
        source_url="https://spb.ginfo.ru/ulicy/kolomyazhskiy_prospekt/34k2/info/",
        entrance="1",
        floor=6,
        apartment="22",
        title="[Демо] Проверить покрытие Wi-Fi",
        work_type="Диагностика сети",
        start_hour=14,
        end_hour=18,
        duration_minutes=45,
    ),
    DemoVisit(
        district="Красногвардейский район",
        street="проспект Энергетиков",
        building="54",
        block="корпус 2",
        latitude="59.9667",
        longitude="30.4348",
        source_url="https://spb.ginfo.ru/ulicy/prospekt_energetikov/54k2/info/",
        entrance="3",
        floor=3,
        apartment="87",
        title="[Демо] Проверить скорость соединения",
        work_type="Диагностика сети",
        start_hour=10,
        end_hour=15,
        duration_minutes=45,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DemoOffice:
    name: str
    city: str
    district: str
    street: str
    building: str
    latitude: str
    longitude: str


DEMO_OFFICES = (
    DemoOffice(
        name="Офис Восток",
        city="Москва",
        district="Восток",
        street="ул Юных Ленинцев",
        building="83с 4",
        latitude="55.702267",
        longitude="37.773852",
    ),
    DemoOffice(
        name="Офис Юго-Восток",
        city="Москва",
        district="Юго-Восток",
        street="ул Бирюлёвская",
        building="1с1",
        latitude="55.601956",
        longitude="37.664752",
    ),
    DemoOffice(
        name="Офис Югоцентр",
        city="Москва",
        district="Югоцентр",
        street="проезд Симферопольский",
        building="7",
        latitude="55.665025",
        longitude="37.615596",
    ),
)


@dataclass(frozen=True)
class SeedResult:
    ticket_id: int
    location_id: int
    address: str
    created: bool


def get_or_create_id(session: Session, find_sql: str, insert_sql: str, parameters: dict) -> int:
    """Execute the literal SQL supplied below; values are always bound separately."""
    existing_id = session.execute(text(find_sql), parameters).scalar_one_or_none()
    if existing_id is not None:
        return existing_id
    return session.execute(text(insert_sql), parameters).scalar_one()


DEMO_SKILLS = (
    "Монтаж ВОЛС",
    "Настройка оборудования",
    "Аварийно-восстановительные работы",
    "Подключение абонентов",
)

DEMO_USERS = (
    {
        "name": "Алексей",
        "surname": "Смирнов",
        "lastname": "Викторович",
        "username": "demo_observer",
        "password": "ObserverSecret123!",
        "role": "observer",
    },
    {
        "name": "Иван",
        "surname": "Петров",
        "lastname": "Иванович",
        "username": "demo_foreman",
        "password": "ForemanSecret123!",
        "role": "foreman",
    },
    {
        "name": "Иван",
        "surname": "Свободный",
        "lastname": "Иванович",
        "username": "demo_foreman_free",
        "password": "ForemanSecret123!",
        "role": "foreman",
    },
    {
        "name": "Дмитрий",
        "surname": "Кузнецов",
        "lastname": "Сергеевич",
        "username": "demo_worker_1",
        "password": "WorkerSecret123!",
        "role": "worker",
        "workshift_start": time(8, 0),
        "workshift_end": time(17, 0),
        "skills": ("Монтаж ВОЛС", "Подключение абонентов"),
    },
    {
        "name": "Михаил",
        "surname": "Новиков",
        "lastname": None,
        "username": "demo_worker_2",
        "password": "WorkerSecret123!",
        "role": "worker",
        "workshift_start": time(22, 0),
        "workshift_end": time(6, 0),
        "skills": ("Аварийно-восстановительные работы", "Монтаж ВОЛС"),
    },
)


def seed_users_and_skills(session: Session) -> None:
    for skill_name in DEMO_SKILLS:
        session.execute(
            text("""
                INSERT INTO worker_skills (skill)
                VALUES (:skill)
                ON CONFLICT (skill) DO NOTHING
            """),
            {"skill": skill_name},
        )

    for user_info in DEMO_USERS:
        existing_id = session.execute(
            text("SELECT id FROM users WHERE lower(username) = lower(:username)"),
            {"username": user_info["username"]},
        ).scalar_one_or_none()

        if existing_id is None:
            user_id = session.execute(
                text("""
                    INSERT INTO users (name, surname, lastname, username, password_hash, role)
                    VALUES (:name, :surname, :lastname, :username, :password_hash, :role)
                    RETURNING id
                """),
                {
                    "name": user_info["name"],
                    "surname": user_info["surname"],
                    "lastname": user_info["lastname"],
                    "username": user_info["username"],
                    "password_hash": hash_password(user_info["password"]),
                    "role": user_info["role"],
                },
            ).scalar_one()

            if user_info["role"] == "worker":
                session.execute(
                    text("""
                        INSERT INTO workers (user_id, workshift_start, workshift_end)
                        VALUES (:user_id, :workshift_start, :workshift_end)
                    """),
                    {
                        "user_id": user_id,
                        "workshift_start": user_info["workshift_start"],
                        "workshift_end": user_info["workshift_end"],
                    },
                )
                for skill_name in user_info["skills"]:
                    skill_id = session.execute(
                        text("SELECT id FROM worker_skills WHERE skill = :skill"),
                        {"skill": skill_name},
                    ).scalar_one()
                    session.execute(
                        text("""
                            INSERT INTO worker_skill_assignments (worker_id, skill_id)
                            VALUES (:worker_id, :skill_id)
                            ON CONFLICT DO NOTHING
                        """),
                        {"worker_id": user_id, "skill_id": skill_id},
                    )


def seed_data(session: Session, visit_date: date) -> list[SeedResult]:
    """Caller owns the transaction. Existing tickets and filled coordinates are preserved."""
    # Serialize copies of this script; the lock is released on commit or rollback.
    session.execute(text("SELECT pg_advisory_xact_lock(20260912, 1)"))
    seed_users_and_skills(session)
    city_id = get_or_create_id(
        session,
        "SELECT id FROM cities WHERE lower(name) = lower(:name)",
        "INSERT INTO cities (name) VALUES (:name) RETURNING id",
        {"name": CITY_NAME},
    )
    results = []
    demo_service_area_id = None
    for visit in DEMO_VISITS:
        district_row_id = get_or_create_id(
            session,
            """
            SELECT id FROM districts
            WHERE city_id = :city_id AND lower(name) = lower(:name)
            """,
            "INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": visit.district},
        )
        service_area_id = session.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{district_row_id}"},
        ).scalar_one()
        if demo_service_area_id is None:
            demo_service_area_id = service_area_id
        street_id = get_or_create_id(
            session,
            """
            SELECT id FROM streets
            WHERE city_id = :city_id AND lower(name) = lower(:name)
            """,
            "INSERT INTO streets (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": visit.street},
        )
        building_id = get_or_create_id(
            session,
            """
            SELECT id FROM buildings
            WHERE street_id = :street_id AND lower(number) = lower(:number)
              AND lower(block) IS NOT DISTINCT FROM lower(CAST(:block AS text))
            """,
            """
            INSERT INTO buildings (city_id, street_id, service_area_id, number, block)
            VALUES (:city_id, :street_id, :service_area_id, :number, :block) RETURNING id
            """,
            {
                "city_id": city_id,
                "street_id": street_id,
                "service_area_id": service_area_id,
                "number": visit.building,
                "block": visit.block,
            },
        )
        existing_service_area_id = session.execute(
            text("SELECT service_area_id FROM buildings WHERE id = :building_id FOR UPDATE"),
            {"building_id": building_id},
        ).scalar_one()
        if existing_service_area_id != service_area_id:
            raise RuntimeError(
                f"У building_id={building_id} уже другая зона обслуживания. "
                "Заполнение отменено: проверьте этот дом вручную."
            )
        entrance_id = None
        if visit.entrance is not None:
            entrance_id = get_or_create_id(
                session,
                """
                SELECT id FROM entrances
                WHERE building_id = :building_id AND lower(number) = lower(:number)
                """,
                """
                INSERT INTO entrances (building_id, number)
                VALUES (:building_id, :number) RETURNING id
                """,
                {"building_id": building_id, "number": visit.entrance},
            )
        destination = {
            "building_id": building_id,
            "entrance_id": entrance_id,
            "apartment": visit.apartment,
        }
        coordinates = {"latitude": Decimal(visit.latitude), "longitude": Decimal(visit.longitude)}
        location = (
            session.execute(
                text("""
                SELECT id, floor, latitude, longitude FROM locations
                WHERE building_id = :building_id
                  AND entrance_id IS NOT DISTINCT FROM CAST(:entrance_id AS integer)
                  AND lower(apartment) IS NOT DISTINCT FROM lower(CAST(:apartment AS text))
                FOR UPDATE
            """),
                destination,
            )
            .mappings()
            .one_or_none()
        )
        if location is None:
            location = (
                session.execute(
                    text("""
                    INSERT INTO locations (
                        building_id, entrance_id, floor, apartment, latitude, longitude
                    ) VALUES (
                        :building_id, :entrance_id, :floor, :apartment, :latitude, :longitude
                    )
                    RETURNING id, floor, latitude, longitude
                """),
                    {**destination, "floor": visit.floor, **coordinates},
                )
                .mappings()
                .one()
            )

        location_id = location["id"]
        if visit.floor is not None:
            if location["floor"] is None:
                session.execute(
                    text("UPDATE locations SET floor = :floor WHERE id = :location_id"),
                    {"floor": visit.floor, "location_id": location_id},
                )
            elif location["floor"] != visit.floor:
                raise RuntimeError(
                    f"У location_id={location_id} уже другой этаж. "
                    "Заполнение отменено: проверьте это место вручную."
                )
        if location["latitude"] is None and location["longitude"] is None:
            session.execute(
                text("""
                    UPDATE locations SET latitude = :latitude, longitude = :longitude
                    WHERE id = :location_id
                """),
                {"location_id": location_id, **coordinates},
            )
        elif (
            location["latitude"] != coordinates["latitude"]
            or location["longitude"] != coordinates["longitude"]
        ):
            raise RuntimeError(
                f"У location_id={location_id} уже другие координаты. "
                "Заполнение отменено: проверьте это место вручную."
            )

        # Natural key for this fixed demo set; dates/statuses are not overwritten on reruns.
        ticket_id = session.execute(
            text("SELECT id FROM tickets WHERE location_id = :location_id AND title = :title"),
            {"location_id": location_id, "title": visit.title},
        ).scalar()
        created = ticket_id is None
        if created:
            wt_row = (
                session.execute(
                    text(
                        "SELECT id, category, default_priority FROM work_types "
                        "WHERE lower(name) = lower(:name) OR lower(code) = lower(:name) "
                        "LIMIT 1"
                    ),
                    {"name": visit.work_type},
                )
                .mappings()
                .one_or_none()
            )
            if wt_row is None:
                wt_row = (
                    session.execute(
                        text(
                            "SELECT id, category, default_priority FROM work_types "
                            "ORDER BY id LIMIT 1"
                        )
                    )
                    .mappings()
                    .one()
                )
            v_start = datetime.combine(visit_date, time(visit.start_hour), MOSCOW_TIME)
            ticket_id = session.execute(
                text("""
                    INSERT INTO tickets (
                        location_id, title, description, work_type, work_type_id,
                        category, priority, received_at,
                        visit_window_start, visit_window_end, estimated_duration_minutes
                    ) VALUES (
                        :location_id, :title, :description, :work_type, :work_type_id,
                        :category, :priority, :received_at,
                        :visit_window_start, :visit_window_end, :estimated_duration_minutes
                    )
                    RETURNING id
                """),
                {
                    "location_id": location_id,
                    "title": visit.title,
                    "description": (
                        "Учебная заявка: подъезд, этаж, квартира, работа, длительность "
                        "и окно визита вымышлены. Дом, корпус и координаты взяты из источника. "
                        "Это не сообщение о реальной неисправности по данному адресу."
                    ),
                    "work_type": visit.work_type,
                    "work_type_id": wt_row["id"],
                    "category": wt_row["category"],
                    "priority": wt_row["default_priority"],
                    "received_at": v_start - timedelta(hours=2),
                    "visit_window_start": v_start,
                    "visit_window_end": datetime.combine(
                        visit_date, time(visit.end_hour), MOSCOW_TIME
                    ),
                    "estimated_duration_minutes": visit.duration_minutes,
                },
            ).scalar_one()

        results.append(
            SeedResult(
                ticket_id=ticket_id,
                location_id=location_id,
                address=visit.address,
                created=created,
            )
        )
    if demo_service_area_id is not None:
        session.execute(
            text("""
                UPDATE workers
                SET service_area_id = COALESCE(service_area_id, :service_area_id)
                WHERE user_id IN (
                    SELECT id FROM users
                    WHERE username IN ('demo_worker_1', 'demo_worker_2')
                )
            """),
            {"service_area_id": demo_service_area_id},
        )
    observer_id = session.execute(
        text("SELECT id FROM users WHERE username = 'demo_observer'")
    ).scalar_one()
    worker_ids = list(
        session.execute(
            text("""
                SELECT w.user_id
                FROM workers AS w
                JOIN users AS u ON u.id = w.user_id
                WHERE u.username IN ('demo_worker_1', 'demo_worker_2')
                ORDER BY u.username
            """)
        ).scalars()
    )
    for index, result in enumerate(results):
        worker_id = worker_ids[index % len(worker_ids)]
        session.execute(
            text("""
                UPDATE tickets SET assigned_worker_id = :worker_id WHERE id = :ticket_id
            """),
            {"ticket_id": result.ticket_id, "worker_id": worker_id},
        )
        existing_comment = session.execute(
            text("""
                SELECT id
                FROM ticket_comments
                WHERE ticket_id = :ticket_id AND author_id = :author_id
                ORDER BY id
                LIMIT 1
            """),
            {"ticket_id": result.ticket_id, "author_id": observer_id},
        ).scalar_one_or_none()
        if existing_comment is None:
            session.execute(
                text("""
                    INSERT INTO ticket_comments (ticket_id, author_id, text)
                    VALUES (:ticket_id, :author_id, :text)
                """),
                {
                    "ticket_id": result.ticket_id,
                    "author_id": observer_id,
                    "text": "Демонстрационная заметка наблюдателя к заявке.",
                },
            )

    # Seed offices and brigades after buildings are created
    for i, office_data in enumerate(DEMO_OFFICES):
        office_city_id = get_or_create_id(
            session,
            "SELECT id FROM cities WHERE lower(name) = lower(:name)",
            "INSERT INTO cities (name) VALUES (:name) RETURNING id",
            {"name": office_data.city},
        )
        district_row_id = get_or_create_id(
            session,
            "SELECT id FROM districts WHERE city_id = :city_id AND lower(name) = lower(:name)",
            "INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": office_city_id, "name": office_data.district},
        )
        service_area_id = session.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{district_row_id}"},
        ).scalar_one()
        street_id = get_or_create_id(
            session,
            "SELECT id FROM streets WHERE city_id = :city_id AND lower(name) = lower(:name)",
            "INSERT INTO streets (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": office_city_id, "name": office_data.street},
        )
        building_id = get_or_create_id(
            session,
            "SELECT id FROM buildings WHERE street_id = :street_id AND lower(number) = lower(:number)",  # noqa: E501
            "INSERT INTO buildings (city_id, street_id, service_area_id, number) VALUES (:city_id, :street_id, :service_area_id, :number) RETURNING id",  # noqa: E501
            {
                "city_id": office_city_id,
                "street_id": street_id,
                "service_area_id": service_area_id,
                "number": office_data.building,
            },
        )

        # Insert location for this office
        location = session.execute(
            text(
                "SELECT id FROM locations WHERE building_id = :building_id AND entrance_id IS NULL AND apartment IS NULL"  # noqa: E501
            ),
            {"building_id": building_id},
        ).scalar_one_or_none()

        if not location:
            location = session.execute(
                text(
                    "INSERT INTO locations (building_id, latitude, longitude) VALUES (:building_id, :latitude, :longitude) RETURNING id"  # noqa: E501
                ),
                {
                    "building_id": building_id,
                    "latitude": office_data.latitude,
                    "longitude": office_data.longitude,
                },
            ).scalar_one()

        service_area_id = session.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{district_id}"},
        ).scalar_one_or_none()

        office_id = get_or_create_id(
            session,
            "SELECT id FROM offices WHERE name = :name",
            "INSERT INTO offices (name, location_id, service_area_id) "
            "VALUES (:name, :location_id, :service_area_id) RETURNING id",
            {
                "name": office_data.name,
                "location_id": location,
                "service_area_id": service_area_id,
            },
        )

        # Only create one brigade per demo for simplicity
        if i == 0:
            foreman_id = session.execute(
                text("SELECT id FROM users WHERE username = 'demo_foreman'")
            ).scalar_one_or_none()
            if foreman_id:
                brigade_id = get_or_create_id(
                    session,
                    "SELECT id FROM brigades WHERE name = 'Альфа'",
                    "INSERT INTO brigades (name, foreman_id, office_id) VALUES ('Альфа', :foreman_id, :office_id) RETURNING id",  # noqa: E501
                    {"foreman_id": foreman_id, "office_id": office_id},
                )
                worker_ids = (
                    session.execute(text("SELECT id FROM users WHERE role = 'worker'"))
                    .scalars()
                    .all()
                )
                for w_id in worker_ids:
                    session.execute(
                        text(
                            "INSERT INTO brigade_members (brigade_id, worker_id) VALUES (:b_id, :w_id) ON CONFLICT DO NOTHING"  # noqa: E501
                        ),
                        {"b_id": brigade_id, "w_id": w_id},
                    )

    # Seed appliances and warehouse stock
    demo_appliances = [
        ("Wi-Fi роутер Beeline SmartBox GIGA", "Гигабитный Wi-Fi роутер", "CLIENT_ROUTER", "шт"),
        ("Оптический терминал GPON ONT", "Абонентский терминал", "CLIENT_ROUTER", "шт"),
        ("Кабель витая пара UTP Cat.5e", "Кабель для абонентской разводки", "CABLE", "м"),
        ("Оптический патчкорд SC/APC 3м", "Оптический патчкорд", "FIBER", "шт"),
        ("Обжимной инструмент (Кримпер)", "Инструмент для монтажника", "TOOL", "шт"),
        ("ТВ-приставка Beeline TV Box", "Медиаплеер 4K", "TV_BOX", "шт"),
        ("Умная колонка", "Колонка с голосовым помощником", "SPEAKER", "шт"),
        ("IP-камера Cloud Cam", "Камера домашнего наблюдения", "IP_CAMERA", "шт"),
    ]

    office_ids = list(session.execute(text("SELECT id FROM offices ORDER BY id")).scalars())
    appliance_ids = {}
    for name, desc, a_type, unit in demo_appliances:
        a_id = session.execute(
            text("SELECT id FROM appliances WHERE lower(name) = lower(:name)"),
            {"name": name},
        ).scalar_one_or_none()
        if a_id is None:
            a_id = session.execute(
                text("""
                    INSERT INTO appliances (name, description, type, unit, is_active)
                    VALUES (:name, :desc, :type, :unit, TRUE)
                    RETURNING id
                """),
                {"name": name, "desc": desc, "type": a_type, "unit": unit},
            ).scalar_one()
        appliance_ids[name] = a_id

        # Populate initial stock in all offices
        for off_id in office_ids:
            initial_stock = 1000 if a_type in ("CABLE", "FIBER") else 25
            session.execute(
                text("""
                    INSERT INTO appliance_stocks (office_id, appliance_id, stock)
                    VALUES (:off_id, :app_id, :stock)
                    ON CONFLICT (office_id, appliance_id) DO NOTHING
                """),
                {"off_id": off_id, "app_id": a_id, "stock": initial_stock},
            )

    # Attach equipment to the first demo ticket if exists
    if results and office_ids:
        first_ticket_id = results[0].ticket_id
        first_office_id = office_ids[0]
        router_id = appliance_ids.get("Wi-Fi роутер Beeline SmartBox GIGA")
        cable_id = appliance_ids.get("Кабель витая пара UTP Cat.5e")
        tool_id = appliance_ids.get("Обжимной инструмент (Кримпер)")

        for app_id, qty in [(router_id, 1), (cable_id, 20), (tool_id, 1)]:
            if app_id is not None:
                session.execute(
                    text("""
                        INSERT INTO ticket_appliances (ticket_id, appliance_id, office_id, quantity)
                        VALUES (:ticket_id, :appliance_id, :office_id, :qty)
                        ON CONFLICT (ticket_id, appliance_id) DO NOTHING
                    """),
                    {
                        "ticket_id": first_ticket_id,
                        "appliance_id": app_id,
                        "office_id": first_office_id,
                        "qty": qty,
                    },
                )

    # Seed push subscriptions
    session.execute(
        text("""
        INSERT INTO push_subscriptions (user_id, token)
        SELECT id, 'demo_push_token_' || username
        FROM users
        ON CONFLICT (token) DO NOTHING
        """)
    )

    # Seed notification events
    if results:
        worker_id = session.execute(
            text("SELECT id FROM users WHERE username = 'demo_worker_1'")
        ).scalar_one_or_none()
        observer_id = session.execute(
            text("SELECT id FROM users WHERE username = 'demo_observer'")
        ).scalar_one_or_none()

        if worker_id:
            exists = session.execute(
                text(
                    "SELECT 1 FROM notification_events WHERE recipient_id = :r AND ticket_id = :t AND kind = 'ticket_assigned'"  # noqa: E501
                ),
                {"r": worker_id, "t": results[0].ticket_id},
            ).scalar_one_or_none()
            if not exists:
                session.execute(
                    text(
                        "INSERT INTO notification_events (recipient_id, ticket_id, kind, data) VALUES (:r, :t, 'ticket_assigned', '{\"address\": \"Демо Адрес\"}')"  # noqa: E501
                    ),
                    {"r": worker_id, "t": results[0].ticket_id},
                )

        if observer_id and len(results) > 1:
            exists = session.execute(
                text(
                    "SELECT 1 FROM notification_events WHERE recipient_id = :r AND ticket_id = :t AND kind = 'ticket_status_changed'"  # noqa: E501
                ),
                {"r": observer_id, "t": results[1].ticket_id},
            ).scalar_one_or_none()
            if not exists:
                session.execute(
                    text(
                        'INSERT INTO notification_events (recipient_id, ticket_id, kind, data) VALUES (:r, :t, \'ticket_status_changed\', \'{"new_status": "in_progress", "old_status": "open"}\')'  # noqa: E501
                    ),
                    {"r": observer_id, "t": results[1].ticket_id},
                )

    return results


def run_seed(engine: Engine, visit_date: date) -> list[SeedResult]:
    """Check schema and commit the entire data set atomically; never create/drop tables."""
    config = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())
    with engine.begin() as connection:
        actual_heads = set(MigrationContext.configure(connection).get_current_heads())
        if actual_heads != expected_heads:
            raise RuntimeError(
                "Сначала примените схему БД: python -m alembic upgrade head. "
                "Затем повторите python seed_demo.py."
            )
        with Session(bind=connection) as session:
            return seed_data(session, visit_date)


def main() -> int:
    parser = argparse.ArgumentParser(description="Заполнить БД демозаявками в Санкт-Петербурге.")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=datetime.now(MOSCOW_TIME).date(),
        help="Дата окон новых заявок, YYYY-MM-DD. По умолчанию сегодня, UTC+03:00.",
    )
    args = parser.parse_args()
    try:
        results = run_seed(get_engine(), args.date)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (SQLAlchemyError, ValidationError):
        print(
            "Не удалось заполнить БД. Изменения этого запуска отменены. "
            "Проверьте PostgreSQL, DATABASE_URL в .env и применённые миграции.",
            file=sys.stderr,
        )
        return 1
    created_count = sum(result.created for result in results)
    print(
        f"Готово. Создано заявок: {created_count}; "
        f"уже существовало: {len(results) - created_count}."
    )
    for result in results:
        print(f"ticket_id={result.ticket_id}; location_id={result.location_id}; {result.address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
