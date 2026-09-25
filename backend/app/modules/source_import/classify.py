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


def work_type_code(bk_type: str) -> str | None:
    return WORK_TYPE_BY_BK.get(normalize(bk_type))


def source_status(bk_status: str) -> str | None:
    return STATUS_BY_BK.get(normalize(bk_status))


def describe() -> dict:
    return {
        "mapping_version": MAPPING_VERSION,
        "work_type_by_bk": WORK_TYPE_BY_BK,
        "skill_by_category": SKILL_BY_CATEGORY,
        "status_by_bk": STATUS_BY_BK,
    }
