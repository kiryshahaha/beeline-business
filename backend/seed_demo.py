"""Fill an existing, migrated database with a Moscow demo day: python seed_demo.py [--date].

The demo covers the three areas of the case («Восток», «Юго-восток», «Югоцентр») with their
offices, one brigade per area and requests of the day at real Moscow addresses. Requests
wait for the planner: the seed assigns nobody and builds no routes.
"""

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
from synthetic_moscow.catalog import (
    APPLIANCE_BY_KEY,
    APPLIANCES,
    REQUIRED_APPLIANCES,
    SKILLS,
    WORK_TYPES,
)
from synthetic_moscow.geography import AREAS

MOSCOW_TIME = timezone(timedelta(hours=3))
CITY_NAME = "Москва"


@dataclass(frozen=True, kw_only=True)
class DemoVisit:
    # The service area of the case; the system shows it as the address district.
    district: str
    street: str
    building: str
    latitude: str
    longitude: str
    source_url: str
    title: str
    work_type: str
    request_type_hd: str
    description: str
    start_hour: int
    end_hour: int
    duration_minutes: int
    start_minute: int = 0
    end_minute: int = 0
    block: str | None = None
    entrance: str | None = None
    floor: int | None = None
    apartment: str | None = None
    # Equipment taken for the visit: (appliance key of the catalog, quantity).
    appliances: tuple[tuple[str, int], ...] = ()
    note: str | None = None

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


# Houses, blocks, entrances, floors counts and coordinates are real OpenStreetMap objects
# (© участники OpenStreetMap, ODbL 1.0), checked on 2026-09-29; source_url opens the object.
# Apartments lie inside the real numbering of the entrance. Requests, clients and people
# are fictional. The first two visits are neighbours in one entrance, the third one returns
# to the first apartment.
DEMO_VISITS = (
    DemoVisit(
        district="Восток",
        street="Средний Золоторожский переулок",
        building="9/11",
        latitude="55.749472",
        longitude="37.679744",
        source_url="https://www.openstreetmap.org/way/49906442",
        entrance="1",
        floor=1,
        apartment="4",
        title="Подключение по конвергентному тарифу",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Подключение по заявке из салона связи. Интернет 100 Мбит/с, клиент просит "
            "аккуратную прокладку в кабель-канале."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент просит позвонить за 30 минут до приезда.",
    ),
    DemoVisit(
        district="Восток",
        street="Средний Золоторожский переулок",
        building="9/11",
        latitude="55.749472",
        longitude="37.679744",
        source_url="https://www.openstreetmap.org/way/49906442",
        entrance="1",
        floor=3,
        apartment="12",
        title="ТВ-приставка не загружается",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="TVE/ENT. Замена приставки техником",
        description=(
            "ТВ-приставка зависает на заставке, сброс не помогает. Заменить приставку и "
            "активировать."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=30,
        appliances=(("tv_box", 1),),
    ),
    DemoVisit(
        district="Восток",
        street="Средний Золоторожский переулок",
        building="9/11",
        latitude="55.749472",
        longitude="37.679744",
        source_url="https://www.openstreetmap.org/way/49906442",
        entrance="1",
        floor=1,
        apartment="4",
        title="Повторный визит: пропадает интернет после подключения",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Разрывы",
        description=(
            "Через неделю после подключения клиент жалуется на разрывы. Проверить обжим "
            "коннектора у роутера и кабель в кабель-канале."
        ),
        start_hour=14,
        end_hour=16,
        duration_minutes=30,
        appliances=(
            ("rj45", 2),
            ("utp", 8),
        ),
    ),
    DemoVisit(
        district="Восток",
        street="улица Авиаконструктора Миля",
        building="8",
        block="корпус 1",
        latitude="55.684793",
        longitude="37.852539",
        source_url="https://www.openstreetmap.org/way/859458572",
        entrance="1",
        floor=1,
        apartment="1",
        title="Конвергенция: интернет и ТВ для абонента мобильной связи",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Абонент мобильной связи подключает домашний интернет 300 Мбит/с. Проложить "
            "кабель от этажного щита до квартиры (около 16 м), установить и настроить "
            "роутер, показать клиенту приложение."
        ),
        start_hour=12,
        end_hour=14,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент просит бахилы и аккуратную прокладку кабеля.",
    ),
    DemoVisit(
        district="Восток",
        street="Денисовский переулок",
        building="8/14",
        latitude="55.766043",
        longitude="37.672556",
        source_url="https://www.openstreetmap.org/way/34319607",
        entrance="3",
        floor=2,
        apartment="47",
        title="Дозаказ ТВ-приставки для второй комнаты",
        work_type="Дозаказ оборудования",
        request_type_hd="Заказ подключения/Дозаказ оборудования",
        description=("Вторая ТВ-приставка в спальню. Кабель от роутера около 22 м."),
        start_hour=16,
        end_hour=18,
        duration_minutes=20,
        appliances=(
            ("rj45", 2),
            ("tv_box", 1),
            ("utp", 5),
        ),
    ),
    DemoVisit(
        district="Восток",
        street="Перовское шоссе",
        building="6А",
        latitude="55.734852",
        longitude="37.743099",
        source_url="https://www.openstreetmap.org/way/50584286",
        entrance="4",
        title="Авария на ТКД: отключение электропитания",
        work_type="Аварий на ТКД",
        request_type_hd="Авария",
        description=(
            "На ТКД в слаботочном шкафу на последнем этаже (подъезд 4) пропало "
            "электропитание, ИБП разряжен. Не работают интернет и ТВ у 25 абонентов. "
            "Проверить автомат в щите и ИБП, при необходимости заменить блок питания "
            "коммутатора."
        ),
        start_hour=0,
        end_hour=23,
        duration_minutes=80,
        start_minute=1,
        end_minute=59,
        appliances=(
            ("psu", 1),
            ("ups", 1),
        ),
    ),
    DemoVisit(
        district="Восток",
        street="Люблинская улица",
        building="35",
        block="корпус 1",
        latitude="55.697889",
        longitude="37.734481",
        source_url="https://www.openstreetmap.org/way/30853951",
        entrance="5",
        floor=8,
        apartment="175",
        title="Подключение по конвергентному тарифу",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Подключение по заявке из салона связи. Интернет 1000 Мбит/с, клиент просит "
            "аккуратную прокладку в кабель-канале."
        ),
        start_hour=18,
        end_hour=20,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент будет дома только после 17:00.",
    ),
    DemoVisit(
        district="Восток",
        street="улица Петра Романова",
        building="3",
        latitude="55.709392",
        longitude="37.680769",
        source_url="https://www.openstreetmap.org/way/63357952",
        entrance="1",
        floor=2,
        apartment="12",
        title="Пропал интернет",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Нет линка",
        description=(
            "Интернет пропал после замены входной двери. Проверить абонентский кабель в "
            "дверном проёме."
        ),
        start_hour=20,
        end_hour=22,
        duration_minutes=30,
        appliances=(("rj45", 2),),
    ),
    DemoVisit(
        district="Юго-восток",
        street="улица Борисовские Пруды",
        building="10",
        block="корпус 4",
        latitude="55.633877",
        longitude="37.739860",
        source_url="https://www.openstreetmap.org/way/40678889",
        entrance="3",
        floor=3,
        apartment="86",
        title="Подключение с дозаказом ТВ-приставки",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Заказ подключения/Дозаказ оборудования",
        description=(
            "Подключение интернета 300 Мбит/с и установка ТВ-приставки 4K. Кабель до ТВ в "
            "гостиной, около 28 м."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 2),
            ("rj45", 2),
            ("router_giga", 1),
            ("tv_box", 1),
            ("utp", 12),
        ),
        note="Клиент просит позвонить за 30 минут до приезда.",
    ),
    DemoVisit(
        district="Юго-восток",
        street="Касимовская улица",
        building="15",
        latitude="55.597104",
        longitude="37.655314",
        source_url="https://www.openstreetmap.org/way/31668751",
        entrance="4",
        floor=3,
        apartment="154",
        title="Пропал интернет",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Нет линка",
        description=(
            "Интернет пропал после замены входной двери. Проверить абонентский кабель в "
            "дверном проёме."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=30,
        appliances=(("rj45", 2),),
    ),
    DemoVisit(
        district="Юго-восток",
        street="Воронежская улица",
        building="8",
        block="корпус 1",
        latitude="55.608417",
        longitude="37.725893",
        source_url="https://www.openstreetmap.org/way/27178127",
        entrance="1",
        floor=9,
        apartment="36",
        title="Работа с кабелем в квартире",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Работа с кабелем",
        description=("Кабель перебит мебелью. Заменить участок кабеля от щита до роутера."),
        start_hour=14,
        end_hour=16,
        duration_minutes=30,
        appliances=(
            ("rj45", 2),
            ("utp", 8),
        ),
    ),
    DemoVisit(
        district="Юго-восток",
        street="улица Мусы Джалиля",
        building="10",
        block="корпус 1",
        latitude="55.626364",
        longitude="37.740358",
        source_url="https://www.openstreetmap.org/way/27644530",
        entrance="2",
        floor=9,
        apartment="82",
        title="Подключение домашнего интернета к мобильному тарифу",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Конвергентный тариф: интернет 1000 Мбит/с и ТВ. Установить роутер и "
            "ТВ-приставку, кабель завести в комнату у окна, около 9 м."
        ),
        start_hour=12,
        end_hour=14,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент просит бахилы и аккуратную прокладку кабеля.",
    ),
    DemoVisit(
        district="Юго-восток",
        street="Востряковский проезд",
        building="15",
        block="корпус 3",
        latitude="55.575965",
        longitude="37.649298",
        source_url="https://www.openstreetmap.org/way/31667734",
        entrance="1",
        floor=6,
        apartment="21",
        title="Дозаказ: IP-камера",
        work_type="Дозаказ оборудования",
        request_type_hd="Дозаказ оборудования",
        description=(
            "Клиент заказал дополнительное оборудование. Доставить, установить и настроить, "
            "показать работу в приложении."
        ),
        start_hour=16,
        end_hour=18,
        duration_minutes=20,
        appliances=(("camera", 1),),
    ),
    DemoVisit(
        district="Юго-восток",
        street="Борисовский проезд",
        building="38",
        block="корпус 1",
        latitude="55.617241",
        longitude="37.727303",
        source_url="https://www.openstreetmap.org/way/27644747",
        entrance="2",
        title="Авария: затопление подвала, узел связи обесточен",
        work_type="Аварий на ТКД",
        request_type_hd="Авария",
        description=(
            "Управляющая компания сообщила о затоплении подвала. ТКД обесточен, без связи "
            "119 абонентов. Выезд совместно с представителем УК, проверить оборудование на "
            "влагу."
        ),
        start_hour=0,
        end_hour=23,
        duration_minutes=80,
        start_minute=1,
        end_minute=59,
        appliances=(
            ("psu", 1),
            ("switch8", 1),
        ),
    ),
    DemoVisit(
        district="Юго-восток",
        street="Ереванская улица",
        building="17",
        block="корпус 1",
        latitude="55.630734",
        longitude="37.674840",
        source_url="https://www.openstreetmap.org/way/31024664",
        entrance="2",
        floor=1,
        apartment="23",
        title="Подключение по конвергентному тарифу",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Конвергентный тариф: интернет 1000 Мбит/с и ТВ. Установить роутер и "
            "ТВ-приставку, кабель завести в комнату у окна, около 18 м."
        ),
        start_hour=18,
        end_hour=20,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент будет дома только после 17:00.",
    ),
    DemoVisit(
        district="Юго-восток",
        street="улица Москворечье",
        building="37",
        block="корпус 1",
        latitude="55.645941",
        longitude="37.661965",
        source_url="https://www.openstreetmap.org/way/36868606",
        entrance="2",
        floor=2,
        apartment="28",
        title="Нет интернета: нет линка на порту",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Нет линка",
        description=(
            "С утра нет интернета, у соседей по стояку работает. Линк на порту отсутствует, "
            "вероятно повреждён кабель в квартире после ремонта."
        ),
        start_hour=20,
        end_hour=22,
        duration_minutes=30,
        appliances=(("rj45", 2),),
    ),
    DemoVisit(
        district="Югоцентр",
        street="Ленинский проспект",
        building="79",
        latitude="55.684260",
        longitude="37.541152",
        source_url="https://www.openstreetmap.org/way/29092200",
        entrance="2",
        floor=3,
        apartment="46",
        title="Конвергенция: интернет и ТВ для абонента мобильной связи",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Абонент мобильной связи подключает домашний интернет 1000 Мбит/с. Проложить "
            "кабель от этажного щита до квартиры (около 26 м), установить и настроить "
            "роутер, показать клиенту приложение."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент просит позвонить за 30 минут до приезда.",
    ),
    DemoVisit(
        district="Югоцентр",
        street="Одесская улица",
        building="22",
        block="корпус 1",
        latitude="55.652818",
        longitude="37.587853",
        source_url="https://www.openstreetmap.org/way/29325263",
        entrance="6",
        floor=4,
        apartment="195",
        title="Рост ошибок на порту",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Рост ошибок на порту",
        description=(
            "Мониторинг: рост CRC-ошибок на порту доступа абонента. Переобжать кабель, при "
            "необходимости заменить патч-корд на щите."
        ),
        start_hour=10,
        end_hour=12,
        duration_minutes=30,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
        ),
    ),
    DemoVisit(
        district="Югоцентр",
        street="Варшавское шоссе",
        building="76",
        block="корпус 2",
        latitude="55.654347",
        longitude="37.618026",
        source_url="https://www.openstreetmap.org/way/36743719",
        entrance="1",
        floor=1,
        apartment="56",
        title="Перенос кабеля и розетки",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="Работа с кабелем",
        description=("Кабель перебит мебелью. Заменить участок кабеля от щита до роутера."),
        start_hour=14,
        end_hour=16,
        duration_minutes=30,
        appliances=(
            ("rj45", 2),
            ("utp", 8),
        ),
    ),
    DemoVisit(
        district="Югоцентр",
        street="Нагорная улица",
        building="18",
        block="корпус 1",
        latitude="55.679611",
        longitude="37.604769",
        source_url="https://www.openstreetmap.org/way/32610839",
        entrance="2",
        floor=5,
        apartment="38",
        title="Подключение с дозаказом ТВ-приставки",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Заказ подключения/Дозаказ оборудования",
        description=(
            "Клиент заказал интернет и приставку. Установить оборудование, проверить каналы "
            "и скорость."
        ),
        start_hour=12,
        end_hour=14,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 2),
            ("rj45", 2),
            ("router_giga", 1),
            ("tv_box", 1),
            ("utp", 12),
        ),
        note="Клиент просит бахилы и аккуратную прокладку кабеля.",
    ),
    DemoVisit(
        district="Югоцентр",
        street="Комсомольский проспект",
        building="14/1",
        block="корпус 3",
        latitude="55.731647",
        longitude="37.589533",
        source_url="https://www.openstreetmap.org/way/45468550",
        entrance="8",
        floor=3,
        apartment="158",
        title="Дозаказ: IP-камера",
        work_type="Дозаказ оборудования",
        request_type_hd="Дозаказ оборудования",
        description=(
            "Клиент заказал дополнительное оборудование. Доставить, установить и настроить, "
            "показать работу в приложении."
        ),
        start_hour=16,
        end_hour=18,
        duration_minutes=20,
        appliances=(("camera", 1),),
    ),
    DemoVisit(
        district="Югоцентр",
        street="улица Винокурова",
        building="6",
        latitude="55.688478",
        longitude="37.585025",
        source_url="https://www.openstreetmap.org/way/35680164",
        entrance="5",
        title="Авария: ошибки на магистральном порту ТКД",
        work_type="Аварий на ТКД",
        request_type_hd="Авария",
        description=(
            "Мониторинг: массовые CRC-ошибки на аплинке коммутатора ТКД на чердаке с 04:54, "
            "у 23 абонентов разрывы и низкая скорость. Заменить SFP-модуль и оптический "
            "патч-корд."
        ),
        start_hour=0,
        end_hour=23,
        duration_minutes=80,
        start_minute=1,
        end_minute=59,
        appliances=(
            ("patch_sc", 1),
            ("sfp", 1),
        ),
    ),
    DemoVisit(
        district="Югоцентр",
        street="Садовническая набережная",
        building="80",
        latitude="55.737357",
        longitude="37.640309",
        source_url="https://www.openstreetmap.org/way/539076050",
        entrance="5",
        floor=4,
        apartment="67",
        title="Подключение домашнего интернета к мобильному тарифу",
        work_type="Подключение клиентов Базовая",
        request_type_hd="Конвергенция абонента",
        description=(
            "Подключение по заявке из салона связи. Интернет 100 Мбит/с, клиент просит "
            "аккуратную прокладку в кабель-канале."
        ),
        start_hour=18,
        end_hour=20,
        duration_minutes=70,
        appliances=(
            ("patch_utp", 1),
            ("rj45", 2),
            ("router_giga", 1),
            ("utp", 10),
        ),
        note="Клиент будет дома только после 17:00.",
    ),
    DemoVisit(
        district="Югоцентр",
        street="Затонная улица",
        building="5",
        block="корпус 3",
        latitude="55.680978",
        longitude="37.685396",
        source_url="https://www.openstreetmap.org/way/31649083",
        entrance="4",
        floor=2,
        apartment="68",
        title="Замена ТВ-приставки",
        work_type="Локальная заявка/ремонт у клиента",
        request_type_hd="TVE/ENT. Замена приставки техником",
        description=(
            "ТВ-приставка зависает на заставке, сброс не помогает. Заменить приставку и "
            "активировать."
        ),
        start_hour=20,
        end_hour=22,
        duration_minutes=30,
        appliances=(("tv_box", 1),),
    ),
)


@dataclass(frozen=True, kw_only=True)
class DemoOffice:
    name: str
    city: str
    district: str
    street: str
    building: str
    block: str | None
    latitude: str
    longitude: str


# The offices of the organizer's day files, one per area.
DEMO_OFFICES = tuple(
    DemoOffice(
        name=area.office.name,
        city=area.office.city,
        district=area.name,
        street=area.office.street,
        building=area.office.number,
        block=area.office.block,
        latitude=f"{area.office.latitude:.6f}",
        longitude=f"{area.office.longitude:.6f}",
    )
    for area in AREAS
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


DEMO_SKILLS = SKILLS
UNIVERSAL = ("Аварийные работы", "Локальные работы", "Работы на подключение и дозаказы")

# Demo passwords work only in a demo database; the Bruno collection relies on them.
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
        "area": "Восток",
    },
    {
        "name": "Олег",
        "surname": "Сорокин",
        "lastname": "Андреевич",
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
        "area": "Восток",
        "workshift_start": time(9, 0),
        "workshift_end": time(18, 0),
        "schedule_type": "5/2",
        "transport_type": "public_transport",
        "skills": (
            "Работы на подключение и дозаказы",
            "Локальные работы",
            "Настройка IPTV и видеонаблюдения",
        ),
    },
    {
        "name": "Михаил",
        "surname": "Новиков",
        "lastname": "Павлович",
        "username": "demo_worker_2",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Восток",
        # Night duty answering outages.
        "workshift_start": time(22, 0),
        "workshift_end": time(6, 0),
        "schedule_type": "2/2",
        "transport_type": "car",
        "skills": (
            "Аварийные работы",
            "Локальные работы",
            "Монтаж и сварка ВОЛС",
            "Допуск по электробезопасности (III группа)",
        ),
    },
    {
        "name": "Сергей",
        "surname": "Воронин",
        "lastname": "Николаевич",
        "username": "demo_foreman_2",
        "password": "ForemanSecret123!",
        "role": "foreman",
        "area": "Юго-восток",
    },
    {
        "name": "Андрей",
        "surname": "Ковалёв",
        "lastname": "Юрьевич",
        "username": "demo_foreman_3",
        "password": "ForemanSecret123!",
        "role": "foreman",
        "area": "Югоцентр",
    },
    {
        "name": "Руслан",
        "surname": "Галиев",
        "lastname": "Маратович",
        "username": "demo_worker_3",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Восток",
        "workshift_start": time(10, 0),
        "workshift_end": time(22, 0),
        "schedule_type": "2/2",
        "transport_type": "car",
        "skills": UNIVERSAL + ("Монтаж и сварка ВОЛС",),
    },
    {
        "name": "Артём",
        "surname": "Белов",
        "lastname": "Олегович",
        "username": "demo_worker_4",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Юго-восток",
        "workshift_start": time(10, 0),
        "workshift_end": time(22, 0),
        "schedule_type": "2/2",
        "transport_type": "car",
        "skills": UNIVERSAL + ("Допуск по электробезопасности (III группа)",),
    },
    {
        "name": "Никита",
        "surname": "Орлов",
        "lastname": "Денисович",
        "username": "demo_worker_5",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Юго-восток",
        "workshift_start": time(9, 0),
        "workshift_end": time(18, 0),
        "schedule_type": "5/2",
        "transport_type": "public_transport",
        "skills": ("Работы на подключение и дозаказы", "Настройка IPTV и видеонаблюдения"),
    },
    {
        "name": "Константин",
        "surname": "Фомин",
        "lastname": "Вадимович",
        "username": "demo_worker_6",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Юго-восток",
        "workshift_start": time(14, 0),
        "workshift_end": time(22, 0),
        "schedule_type": "5/2",
        "transport_type": "walking",
        "skills": ("Локальные работы",),
    },
    {
        "name": "Павел",
        "surname": "Зайцев",
        "lastname": "Игоревич",
        "username": "demo_worker_7",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Югоцентр",
        "workshift_start": time(10, 0),
        "workshift_end": time(22, 0),
        "schedule_type": "2/2",
        "transport_type": "car",
        "skills": UNIVERSAL,
    },
    {
        "name": "Егор",
        "surname": "Лебедев",
        "lastname": "Романович",
        "username": "demo_worker_8",
        "password": "WorkerSecret123!",
        "role": "worker",
        "area": "Югоцентр",
        "workshift_start": time(9, 0),
        "workshift_end": time(21, 0),
        "schedule_type": "2/2",
        "transport_type": "bicycle",
        "skills": ("Локальные работы", "Работы на подключение и дозаказы"),
    },
)


def seed_users_and_skills(session: Session, visit_date: date) -> None:
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
        if existing_id is not None:
            continue
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
        if user_info["role"] != "worker":
            continue
        two_two = user_info["schedule_type"] == "2/2"
        session.execute(
            text("""
                INSERT INTO workers (
                    user_id, workshift_start, workshift_end, transport_type,
                    schedule_type, cycle_start_date, workdays_mask
                ) VALUES (
                    :user_id, :workshift_start, :workshift_end, :transport_type,
                    :schedule_type, :cycle_start_date, CAST(:workdays_mask AS JSONB)
                )
            """),
            {
                "user_id": user_id,
                "workshift_start": user_info["workshift_start"],
                "workshift_end": user_info["workshift_end"],
                "transport_type": user_info["transport_type"],
                "schedule_type": user_info["schedule_type"],
                # The demo day is the first working day of a 2/2 cycle.
                "cycle_start_date": visit_date if two_two else None,
                "workdays_mask": None if two_two else "[0, 1, 2, 3, 4]",
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


def demo_area_office(session: Session, service_area_id, results, *, fallback: int) -> int:
    """The office of a service area, where its demo brigade works.

    The demo engineers serve the area of their requests. Their brigade must belong to the
    same area, otherwise their profile and brigade would state two areas and the planner
    would rightly refuse them.
    """
    if service_area_id is None or not results:
        return fallback
    existing = session.execute(
        text("SELECT id FROM offices WHERE service_area_id = :area_id"),
        {"area_id": service_area_id},
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return session.execute(
        text("""
            INSERT INTO offices (name, location_id, service_area_id)
            VALUES ('Офис участка демо-заявок', :location_id, :area_id)
            RETURNING id
        """),
        {"location_id": results[0].location_id, "area_id": service_area_id},
    ).scalar_one()


def area_ids(session: Session, city_id: int) -> dict[str, int]:
    """District of the city -> its service area (the district trigger creates both)."""
    result = {}
    for area in AREAS:
        district_row_id = get_or_create_id(
            session,
            """
            SELECT id FROM districts
            WHERE city_id = :city_id AND lower(name) = lower(:name)
            """,
            "INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": area.name},
        )
        result[area.name] = session.execute(
            text("SELECT id FROM service_areas WHERE code = :code"),
            {"code": f"district_{district_row_id}"},
        ).scalar_one()
    return result


def seed_work_type_requirements(session: Session, observer_id: int) -> None:
    """The planner needs a rule, skills and equipment for each work type of the case."""
    for spec in WORK_TYPES:
        work_type_id = session.execute(
            text("SELECT id FROM work_types WHERE lower(name) = lower(:name)"),
            {"name": spec.name},
        ).scalar_one_or_none()
        if work_type_id is None:
            continue
        session.execute(
            text("""
                INSERT INTO work_type_planning_rules
                    (work_type_id, service_duration_source, configured_by)
                VALUES (:work_type_id, 'work_norm', :observer_id)
                ON CONFLICT (work_type_id) DO NOTHING
            """),
            {"work_type_id": work_type_id, "observer_id": observer_id},
        )
        session.execute(
            text("""
                INSERT INTO work_type_required_skills (work_type_id, skill_id)
                SELECT :work_type_id, id FROM worker_skills WHERE skill = :skill
                ON CONFLICT DO NOTHING
            """),
            {"work_type_id": work_type_id, "skill": spec.skill},
        )
        for key, quantity in REQUIRED_APPLIANCES.get(spec.code, ()):
            session.execute(
                text("""
                    INSERT INTO work_type_required_appliances
                        (work_type_id, appliance_id, quantity)
                    SELECT :work_type_id, id, :quantity FROM appliances
                    WHERE lower(name) = lower(:name)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "work_type_id": work_type_id,
                    "quantity": quantity,
                    "name": APPLIANCE_BY_KEY[key].name,
                },
            )


def seed_appliances(session: Session) -> dict[str, int]:
    appliance_ids = {}
    for spec in APPLIANCES:
        appliance_id = session.execute(
            text("SELECT id FROM appliances WHERE lower(name) = lower(:name)"),
            {"name": spec.name},
        ).scalar_one_or_none()
        if appliance_id is None:
            appliance_id = session.execute(
                text("""
                    INSERT INTO appliances (name, description, type, unit, is_active)
                    VALUES (:name, :description, :type, :unit, :is_active)
                    RETURNING id
                """),
                {
                    "name": spec.name,
                    "description": spec.description,
                    "type": spec.type,
                    "unit": spec.unit,
                    "is_active": spec.is_active,
                },
            ).scalar_one()
        appliance_ids[spec.key] = appliance_id
    return appliance_ids


def initial_stock(key: str) -> int:
    spec = APPLIANCE_BY_KEY[key]
    if spec.unit == "м":
        return 1000
    if spec.type == "TOOL":
        return 4
    if key in ("rj45", "patch_utp", "patch_sc"):
        return 200
    return 25 if spec.is_active else 6


def seed_data(session: Session, visit_date: date) -> list[SeedResult]:
    """Caller owns the transaction. Existing tickets and filled coordinates are preserved."""
    # Serialize copies of this script; the lock is released on commit or rollback.
    session.execute(text("SELECT pg_advisory_xact_lock(20260912, 1)"))
    seed_users_and_skills(session, visit_date)
    city_id = get_or_create_id(
        session,
        "SELECT id FROM cities WHERE lower(name) = lower(:name)",
        "INSERT INTO cities (name) VALUES (:name) RETURNING id",
        {"name": CITY_NAME},
    )
    areas = area_ids(session, city_id)
    results = []
    visit_areas = []
    for visit in DEMO_VISITS:
        if visit.district not in areas:
            areas[visit.district] = area_ids_for_extra_district(session, city_id, visit.district)
        service_area_id = areas[visit.district]
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
            v_start = datetime.combine(
                visit_date, time(visit.start_hour, visit.start_minute), MOSCOW_TIME
            )
            v_end = datetime.combine(
                visit_date, time(visit.end_hour, visit.end_minute), MOSCOW_TIME
            )
            emergency = wt_row["category"] == "emergency"
            # Outages come in on the morning of the day, other requests the evening before.
            received = (
                datetime.combine(visit_date, time(7, 20), MOSCOW_TIME)
                if emergency
                else v_start - timedelta(hours=15)
            )
            ticket_id = session.execute(
                text("""
                    INSERT INTO tickets (
                        location_id, service_area_id, title, description, work_type,
                        work_type_id, category, priority, received_at, sla_deadline_at,
                        response_deadline_at, request_type_hd, service_duration_source,
                        visit_window_start, visit_window_end, estimated_duration_minutes
                    ) VALUES (
                        :location_id, :service_area_id, :title, :description, :work_type,
                        :work_type_id, :category, :priority, :received_at, :sla_deadline_at,
                        :response_deadline_at, :request_type_hd, 'work_norm',
                        :visit_window_start, :visit_window_end, :estimated_duration_minutes
                    )
                    RETURNING id
                """),
                {
                    "location_id": location_id,
                    "service_area_id": service_area_id,
                    "title": visit.title,
                    "description": visit.description,
                    "work_type": visit.work_type,
                    "work_type_id": wt_row["id"],
                    "category": wt_row["category"],
                    "priority": wt_row["default_priority"],
                    "received_at": received,
                    "sla_deadline_at": received + timedelta(hours=24) if emergency else None,
                    "response_deadline_at": (received + timedelta(hours=2) if emergency else None),
                    "request_type_hd": visit.request_type_hd,
                    "visit_window_start": v_start,
                    "visit_window_end": v_end,
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
        visit_areas.append(service_area_id)

    observer_id = session.execute(
        text("SELECT id FROM users WHERE username = 'demo_observer'")
    ).scalar_one()
    for visit, result in zip(DEMO_VISITS, results, strict=True):
        if visit.note is None:
            continue
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
                {"ticket_id": result.ticket_id, "author_id": observer_id, "text": visit.note},
            )

    # Offices after the requests: location 1 stays the first demo request.
    office_ids = {}
    for office_data in DEMO_OFFICES:
        service_area_id = areas[office_data.district]
        street_id = get_or_create_id(
            session,
            "SELECT id FROM streets WHERE city_id = :city_id AND lower(name) = lower(:name)",
            "INSERT INTO streets (city_id, name) VALUES (:city_id, :name) RETURNING id",
            {"city_id": city_id, "name": office_data.street},
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
                "number": office_data.building,
                "block": office_data.block,
            },
        )
        location = get_or_create_id(
            session,
            """
            SELECT id FROM locations
            WHERE building_id = :building_id AND entrance_id IS NULL AND apartment IS NULL
            """,
            """
            INSERT INTO locations (building_id, latitude, longitude)
            VALUES (:building_id, :latitude, :longitude) RETURNING id
            """,
            {
                "building_id": building_id,
                "latitude": office_data.latitude,
                "longitude": office_data.longitude,
            },
        )
        office_ids[office_data.district] = get_or_create_id(
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

    # One brigade per area: its foreman, engineers and the area office.
    for user_info in DEMO_USERS:
        if user_info["role"] == "worker":
            session.execute(
                text("""
                    UPDATE workers
                    SET service_area_id = COALESCE(service_area_id, :service_area_id),
                        stock_office_id = COALESCE(stock_office_id, :office_id)
                    WHERE user_id = (SELECT id FROM users WHERE username = :username)
                """),
                {
                    "service_area_id": areas[user_info["area"]],
                    "office_id": office_ids[user_info["area"]],
                    "username": user_info["username"],
                },
            )
    for user_info in DEMO_USERS:
        if user_info["role"] != "foreman" or "area" not in user_info:
            continue
        foreman_id = session.execute(
            text("SELECT id FROM users WHERE username = :username"),
            {"username": user_info["username"]},
        ).scalar_one()
        brigade_id = get_or_create_id(
            session,
            "SELECT id FROM brigades WHERE foreman_id = :foreman_id",
            "INSERT INTO brigades (name, foreman_id, office_id) "
            "VALUES (:name, :foreman_id, :office_id) RETURNING id",
            {
                "name": (
                    f"Бригада {user_info['surname']} "
                    f"{user_info['name'][0]}. {user_info['lastname'][0]}."
                ),
                "foreman_id": foreman_id,
                "office_id": demo_area_office(
                    session,
                    areas[user_info["area"]],
                    results,
                    fallback=office_ids[user_info["area"]],
                ),
            },
        )
        for member in DEMO_USERS:
            if member["role"] == "worker" and member["area"] == user_info["area"]:
                session.execute(
                    text("""
                        INSERT INTO brigade_members (brigade_id, worker_id)
                        SELECT :brigade_id, id FROM users WHERE username = :username
                        ON CONFLICT DO NOTHING
                    """),
                    {"brigade_id": brigade_id, "username": member["username"]},
                )

    appliance_ids = seed_appliances(session)
    seed_work_type_requirements(session, observer_id)
    for office_id in office_ids.values():
        for key, appliance_id in appliance_ids.items():
            session.execute(
                text("""
                    INSERT INTO appliance_stocks (office_id, appliance_id, stock)
                    VALUES (:office_id, :appliance_id, :stock)
                    ON CONFLICT (office_id, appliance_id) DO NOTHING
                """),
                {"office_id": office_id, "appliance_id": appliance_id, "stock": initial_stock(key)},
            )
    area_offices = {area_id: office_ids[name] for name, area_id in areas.items()}
    for visit, result, area_id in zip(DEMO_VISITS, results, visit_areas, strict=True):
        for key, quantity in visit.appliances:
            session.execute(
                text("""
                    INSERT INTO ticket_appliances (ticket_id, appliance_id, office_id, quantity)
                    VALUES (:ticket_id, :appliance_id, :office_id, :quantity)
                    ON CONFLICT (ticket_id, appliance_id) DO NOTHING
                """),
                {
                    "ticket_id": result.ticket_id,
                    "appliance_id": appliance_ids[key],
                    "office_id": area_offices[area_id],
                    "quantity": quantity,
                },
            )

    # Push tokens of demo accounts for the notification demo.
    session.execute(
        text("""
        INSERT INTO push_subscriptions (user_id, token)
        SELECT id, 'demo_push_token_' || username
        FROM users
        WHERE username LIKE 'demo\\_%'
        ON CONFLICT (token) DO NOTHING
        """)
    )
    return results


def area_ids_for_extra_district(session: Session, city_id: int, name: str) -> int:
    """A visit of a patched demo set may name a district outside the three areas."""
    district_row_id = get_or_create_id(
        session,
        "SELECT id FROM districts WHERE city_id = :city_id AND lower(name) = lower(:name)",
        "INSERT INTO districts (city_id, name) VALUES (:city_id, :name) RETURNING id",
        {"city_id": city_id, "name": name},
    )
    return session.execute(
        text("SELECT id FROM service_areas WHERE code = :code"),
        {"code": f"district_{district_row_id}"},
    ).scalar_one()


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
    parser = argparse.ArgumentParser(description="Заполнить БД демонстрационным днём в Москве.")
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
