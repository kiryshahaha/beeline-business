"""Fictional files in the organizer's day format: cp1251, «;», office address below."""

import csv
import hashlib
import io

import httpx

DEMAND_HEADER = [
    "Заявка",
    "Тип заявки BK",
    "Тип заявки HD",
    "Начало",
    "Окончание",
    "Район",
    "Адрес",
    "Подключение",
    "Гигабитное подключение",
]
CONTROL_HEADER = [
    "Заявка",
    "Тип заявки BK",
    "Статус BK",
    "Тип заявки HD",
    "Начало",
    "Окончание",
    "Район",
    "Адрес",
    "Бригада",
    "Подключение",
    "Гигабитное подключение",
]
OFFICE = "г. Москва, ул Учебная, д 5с 1"
# id, BK, HD, start, end, district, address, apartment, brigade, BK status
VISITS = [
    (
        "101",
        "Подключение",
        "Конвергенция абонента",
        "10.09.2026 10:00",
        "10.09.2026 12:00",
        "Центральный",
        "Город Москва, ул.Вымышленная, д. 1 к 2",
        "5",
        "Бригада Тестов",
        "Выполнена",
    ),
    (
        "102",
        "Локальная заявка",
        "Нет линка",
        "10.09.2026 12:00",
        "10.09.2026 14:00",
        "Центральный",
        "г.Город Москва, пр-кт.Учебный, д. 7",
        "12",
        "Бригада Тестов",
        "Отменена",
    ),
    (
        "103",
        "Глобальная проблема",
        "Информация",
        "10.09.2026 0:01",
        "10.09.2026 23:59",
        "Южный",
        "МО, г. Учебногорск Садовая ул. д. 3/1",
        None,
        "Бригада Пробный",
        "В пути",
    ),
    (
        "104",
        "Дозаказ",
        "Дозаказ оборудования",
        "10.09.2026 14:00",
        "10.09.2026 16:00",
        "Южный",
        "Домодедово, проезд.Опытный 1-й, д. 2А",
        "44",
        "Пробный Иван",
        "Просрочена",
    ),
    (
        "105",
        "Подключение",
        "Заявка на подключение",
        "10.09.2026 16:00",
        "10.09.2026 18:00",
        "Центральный",
        "Город Москва, б-р.Тестовый Квартал 12а, д. к3",
        "25",
        "",
        "Не отправлена",
    ),
    (
        "106",
        "Локальная заявка",
        "Работа с кабелем",
        "10.09.2026 18:00",
        "10.09.2026 20:00",
        "Центральный",
        "Город Москва, ул.Вымышленная, д. 1 к 2",
        "9",
        "Бригада Тестов",
        "В работе",
    ),
]


def _csv(rows: list[list[str]], encoding: str = "cp1251", delimiter: str = ";") -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, delimiter=delimiter, lineterminator="\r\n").writerows(rows)
    return stream.getvalue().encode(encoding)


def demand_rows(visits=VISITS, prefix: str = "") -> list[list[str]]:
    return [
        [
            prefix + v[0],
            v[1],
            v[2],
            v[3],
            v[4],
            v[5],
            v[6],
            "FMC" if v[1] == "Подключение" else "",
            "Нет",
        ]
        for v in visits
    ]


def demand_csv(visits=VISITS, office: str | None = OFFICE, extra=(), **options) -> bytes:
    rows = [DEMAND_HEADER, *demand_rows(visits), *extra]
    if office is not None:
        width = len(DEMAND_HEADER)
        rows += [[""] * width, [""] * width, ["Адрес Офиса", office] + [""] * (width - 2)]
    return _csv(rows, **options)


def control_csv(visits=VISITS, extra=()) -> bytes:
    rows = [CONTROL_HEADER]
    for v in visits:
        address = v[6] + (f", кв. {v[7]}" if v[7] else "")
        rows.append(
            [
                "3000" + v[0],
                v[1],
                v[9],
                v[2],
                v[3],
                v[4],
                v[5],
                address,
                v[8],
                "FMC" if v[1] == "Подключение" else "",
                "Нет",
            ]
        )
    return _csv(rows + list(extra))


def geocode_response(request: httpx.Request) -> httpx.Response:
    """Deterministic Moscow points; «Квартал» answers weakly, «Нигдеевка» is not found."""
    text = request.url.params["text"]
    if "Нигдеевка" in text:
        return httpx.Response(200, json={"results": []})
    digest = hashlib.sha256(text.encode()).digest()
    weak = "Квартал" in text
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "lat": round(55.60 + digest[0] / 255 * 0.3, 6),
                    "lon": round(37.40 + digest[1] / 255 * 0.4, 6),
                    "result_type": "street" if weak else "building",
                    "rank": {"confidence": 0.5 if weak else 1},
                }
            ]
        },
    )
