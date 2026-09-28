"""Versioned mapping of source classifiers onto the project catalog.

BK (Beekeeper) and HD (HelpDesk) are source systems, not kinds of work (C23). The BK type
names one of the four organizer norms, so it selects the work type; the HD type is a finer
helpdesk label of the same visit and is kept as provenance. Every row is a visit (M21),
including «Информация» and «Мониторинг»: a type missing here is rejected, never guessed.
"""

from app.modules.source_import.profile import normalize

MAPPING_VERSION = 1

# BK type -> work_types.code (the norms of «Нормативы.xlsx», migration 0011).
WORK_TYPE_BY_BK = {
    "подключение": "connection",
    "дозаказ": "additional",
    "локальная заявка": "repair",
    "глобальная проблема": "emergency",
}

# The three skills of the case (section 2.4.1) by work type category.
SKILL_BY_CATEGORY = {
    "repair": "Локальные работы",
    "connection": "Работы на подключение и дозаказы",
    "additional": "Работы на подключение и дозаказы",
    "emergency": "Аварийные работы",
}

# BK status of the control file -> what happened to the visit that day.
STATUS_BY_BK = {
    "не отправлена": "not_dispatched",
    "отправлена": "dispatched",
    "в пути": "en_route",
    "в работе": "in_progress",
    "выполнена": "completed",
    "отменена": "cancelled",
    "просрочена": "overdue",
}
FINAL_STATUSES = frozenset({"completed", "cancelled", "overdue"})

# HelpDesk request types that explicitly define an emergency visit.
EMERGENCY_HD_TYPES = frozenset(
    {
        "авария",
        "аварийная заявка",
        "аварийные работы",
        "инцидент",
        "массовая авария",
        "авария на сети",
        "emergency",
    }
)

# Known non-emergency HelpDesk types from real/sample organizer datasets.
NON_EMERGENCY_HD_TYPES = frozenset(
    {
        "конвергенция абонента",
        "нет линка",
        "информация",
        "дозаказ оборудования",
        "заявка на подключение",
        "работа с кабелем",
        "подключение",
        "дозаказ",
        "ремонт",
        "локальная заявка",
        "мониторинг",
        "консультация",
        "настройка оборудования",
        "плановые работы",
        "диагностика",
    }
)

KNOWN_HD_TYPES = EMERGENCY_HD_TYPES | NON_EMERGENCY_HD_TYPES


def work_type_code(bk_type: str) -> str | None:
    return WORK_TYPE_BY_BK.get(normalize(bk_type))


def source_status(bk_status: str) -> str | None:
    return STATUS_BY_BK.get(normalize(bk_status))


def is_emergency_hd(hd_type: str | None) -> bool:
    if not hd_type:
        return False
    return normalize(hd_type) in EMERGENCY_HD_TYPES


def is_known_hd(hd_type: str | None) -> bool:
    if not hd_type:
        return False
    return normalize(hd_type) in KNOWN_HD_TYPES


def describe() -> dict:
    return {
        "mapping_version": MAPPING_VERSION,
        "work_type_by_bk": WORK_TYPE_BY_BK,
        "skill_by_category": SKILL_BY_CATEGORY,
        "status_by_bk": STATUS_BY_BK,
        "emergency_hd_types": sorted(EMERGENCY_HD_TYPES),
        "known_hd_types": sorted(KNOWN_HD_TYPES),
    }
