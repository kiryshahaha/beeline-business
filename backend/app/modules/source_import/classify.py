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


class ClassificationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def classify_demand(
    request_type_hd: str | None,
    work_type_category: str | None = None,
    explicit_category: str | None = None,
) -> tuple[str, bool]:
    """Classify incoming demand into a normalized category without free-text heuristics.

    Returns: (category, is_emergency)

    Rules (T4-01):
    1. Positive and negative cases are strictly classified by request_type_hd.
    2. Empty request_type_hd:
       - Never assumed to be an emergency silently.
       - Takes explicit_category if not emergency, or falls back to work_type_category or 'repair'.
       - If explicit_category is 'emergency' but request_type_hd is missing, rejects with
         ClassificationError('emergency_hd_type_required').
    3. Unknown request_type_hd (when provided):
       - Rejects with ClassificationError('unknown_hd_type').
    4. Conflicting classification:
       - HD type is emergency but explicit_category is non-emergency, OR
       - HD type is non-emergency but explicit_category is emergency ->
         ClassificationError('category_classification_conflict').
    """
    norm_hd = normalize(request_type_hd) if request_type_hd else None

    if norm_hd is not None:
        if norm_hd not in KNOWN_HD_TYPES:
            raise ClassificationError(
                "unknown_hd_type",
                f"Неизвестный тип заявки HD: '{request_type_hd}' не входит в перечень",
            )
        if norm_hd in EMERGENCY_HD_TYPES:
            if explicit_category and explicit_category != "emergency":
                raise ClassificationError(
                    "category_classification_conflict",
                    f"Конфликт классификации: признак HD '{request_type_hd}' определяет аварию, "
                    f"но указана категория '{explicit_category}'",
                )
            return ("emergency", True)
        else:
            if explicit_category == "emergency":
                raise ClassificationError(
                    "category_classification_conflict",
                    f"Конфликт классификации: признак HD '{request_type_hd}' не является аварией, "
                    f"но указана категория 'emergency'",
                )
            cat = (
                explicit_category
                or (work_type_category if work_type_category != "emergency" else "repair")
                or "repair"
            )
            return (cat, False)

    # Empty / None request_type_hd
    if explicit_category == "emergency":
        raise ClassificationError(
            "emergency_hd_type_required",
            "Для аварийной заявки обязательно указание request_type_hd из перечня аварийных",
        )
    cat = (
        explicit_category
        or (work_type_category if work_type_category != "emergency" else "repair")
        or "repair"
    )
    return (cat, False)
