"""Structured planning explanations: stable code, short Russian text and the checked values.

Every rejection, worker exclusion and visit factor has the same shape, so a screen can
render them without knowing the solver. Texts state only what was actually checked.
"""

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")

TRANSPORT = {
    "car": "автомобиль",
    "walking": "пешком",
    "bicycle": "велосипед",
    "public_transport": "общественный транспорт",
}
PROFILE = {
    "drive": "автомобиль",
    "walk": "пешком",
    "bicycle": "велосипед",
    "approximated_transit": "общественный транспорт",
}
STATUS = {
    "planned": "запланирована",
    "in_progress": "в работе",
    "completed": "выполнена",
    "wont_fix": "отменена",
}
OBJECTIVE = {
    "unassigned_total": "больше назначенных заявок",
    "travel_minutes": "меньше минут в пути",
}
# Short phrases used when several engineers are rejected for different reasons.
LABELS = {
    "missing_skill": "нет навыка",
    "office_mismatch": "оборудование в другом офисе",
    "window_outside_shift": "окно вне смены",
    "service_after_shift_end": "работа не успевает до конца смены",
    "unreachable_by_transport": "адрес недоступен для его транспорта",
    "address_unreachable": "адрес недостижим",
    "arrival_after_window": "не успевает к окну",
    "return_after_shift_end": "не успевает завершить маршрут до конца смены",
    "route_full": "маршрут заполнен",
}
# Plans saved before structured reasons stored only the code.
LEGACY = {
    "ticket_not_planned": ("ticket_state", "Заявка не в статусе planned"),
    "already_assigned": ("ticket_state", "Заявка уже назначена"),
    "missing_coordinates": ("data", "Нет координат адреса"),
    "unknown_work_type": ("data", "Вид работ не найден в справочнике"),
    "work_requirements_not_configured": ("data", "Не настроены требования вида работ"),
    "invalid_service_duration": ("data", "Недопустимая длительность обслуживания"),
    "outside_shift_horizon": ("time", "Окно визита вне смен дня расчёта"),
    "equipment_not_reserved": ("inventory", "Не зарезервировано оборудование"),
    "stock_inconsistent": ("inventory", "Резерв оборудования расходится с остатком"),
    "no_eligible_worker": ("mixed", "Нет подходящего инженера"),
    "not_selected_by_solver": ("search", "Решатель не включил заявку в план"),
    "invalid_worker_role": ("data", "Пользователь не является инженером"),
    "worker_offline": ("availability", "Инженер снят с линии"),
    "worker_unavailable": ("availability", "Инженер недоступен до конца смены"),
    "worker_en_route": ("availability", "Инженер уже направляется к заявке"),
    "missing_office": ("data", "Инженер не привязан к офису"),
    "shift_already_started": ("availability", "Смена уже началась"),
    "unsupported_transport_profile": ("transport", "Неподдерживаемый транспорт"),
    "worker_busy": ("availability", "Инженер занят другой заявкой"),
}


def explain(code, category, message, *, constraint=None, ids=None, observed=None, required=None):
    return {
        "code": code,
        "category": category,
        "message": message,
        "constraint": constraint,
        "ids": {key: sorted(set(values)) for key, values in (ids or {}).items() if values},
        "observed": observed,
        "required": required,
    }


def iso(value: datetime) -> str:
    return value.astimezone(MOSCOW).isoformat()


def clock(value: datetime, day: date) -> str:
    local = value.astimezone(MOSCOW)
    return local.strftime("%H:%M" if local.date() == day else "%d.%m %H:%M")


def numbers(values) -> str:
    return ", ".join(f"№{value}" for value in sorted(values))


def plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} {one}"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return f"{count} {few}"
    return f"{count} {many}"


def engineers(count: int) -> str:
    return plural(count, "инженер", "инженера", "инженеров")


def genitive(count: int, one: str, many: str) -> str:
    """Form after «из N»: из 1 инженера, из 4 инженеров, из 21 инженера."""
    return f"{count} {one if count % 10 == 1 and count % 100 != 11 else many}"


def legacy(code: str) -> dict:
    category, message = LEGACY.get(code, ("data", "Причина без подробностей"))
    return explain(code, category, message)


def legacy_public(public: dict) -> dict:
    """Read a stored plan; results saved before structured reasons kept only codes."""
    if "outcome" in public:
        return public
    upgraded = dict(public)
    upgraded["unassigned"] = [
        {"ticket_id": x["ticket_id"], "reason": legacy(x["reason"]), "candidates": []}
        for x in public["unassigned"]
    ]
    upgraded["excluded_workers"] = [
        {"worker_id": x["worker_id"], "reason": legacy(x["reason"])}
        for x in public["excluded_workers"]
    ]
    upgraded["outcome"] = (
        "empty" if not public["routes"] else "partial" if public["unassigned"] else "complete"
    )
    return upgraded


# Worker availability ---------------------------------------------------------


def invalid_worker_role(role):
    return explain(
        "invalid_worker_role",
        "data",
        "Пользователь не является инженером",
        observed={"role": role},
        required={"role": "worker"},
    )


def worker_offline():
    return explain(
        "worker_offline",
        "availability",
        "Инженер снят с линии",
        constraint="is_on_line",
        observed={"is_on_line": False},
        required={"is_on_line": True},
    )


def worker_unavailable(expected_available_at=None):
    return explain(
        "worker_unavailable",
        "availability",
        "Инженер недоступен до конца смены",
        constraint="eligible_workers=available_for_remaining_shift",
        observed={"expected_available_at": iso(expected_available_at)}
        if expected_available_at is not None
        else None,
    )


def worker_en_route(ticket_id=None):
    return explain(
        "worker_en_route",
        "availability",
        "Инженер уже направляется к заявке",
        constraint="eligible_workers=without_active_execution",
        ids={"ticket_ids": [ticket_id]} if ticket_id is not None else None,
    )


def missing_office():
    return explain(
        "missing_office",
        "data",
        "Инженер не состоит в бригаде с офисом, точка выезда неизвестна",
    )


def office_without_coordinates(office_id, location_id):
    return explain(
        "missing_coordinates",
        "data",
        f"У адреса офиса №{office_id} нет координат",
        ids={"office_ids": [office_id], "location_ids": [location_id]},
    )


def shift_already_started(shift_start, now, day):
    return explain(
        "shift_already_started",
        "availability",
        f"Смена началась в {clock(shift_start, day)}: расчёт планирует только"
        " ещё не начавшиеся смены",
        constraint="eligible_workers=unstarted_shift_without_overlapping_assignment",
        observed={"calculated_at": iso(now)},
        required={"calculated_before": iso(shift_start)},
    )


def unsupported_transport(transport_type, supported):
    return explain(
        "unsupported_transport_profile",
        "transport",
        f"Транспорт «{transport_type}» не поддерживается расчётом маршрутов",
        observed={"transport_type": transport_type},
        required={"transport_types": sorted(supported)},
    )


def worker_busy(job, busy_from, busy_to, day):
    if job["status"] == "in_progress":
        message = f"Выполняет заявку №{job['id']}"
    else:
        message = (
            f"Занят заявкой №{job['id']} с {clock(busy_from, day)} до {clock(busy_to, day)},"
            " она пересекается со сменой"
        )
    return explain(
        "worker_busy",
        "availability",
        message,
        constraint="eligible_workers=unstarted_shift_without_overlapping_assignment",
        ids={"ticket_ids": [job["id"]]},
        observed={"status": job["status"], "busy_from": iso(busy_from), "busy_to": iso(busy_to)},
    )


# Ticket precheck -------------------------------------------------------------


def ticket_not_planned(status):
    return explain(
        "ticket_not_planned",
        "ticket_state",
        f"Заявка {STATUS.get(status, status)}; планируются только заявки в статусе planned",
        constraint="eligible_tickets=unassigned_planned",
        observed={"status": status},
        required={"status": "planned"},
    )


def already_assigned(worker_ids):
    return explain(
        "already_assigned",
        "ticket_state",
        f"Заявка уже назначена: {numbers(worker_ids)}",
        constraint="eligible_tickets=unassigned_planned",
        ids={"worker_ids": worker_ids},
    )


def ticket_without_coordinates(location_id):
    return explain(
        "missing_coordinates",
        "data",
        "У адреса заявки нет координат",
        ids={"location_ids": [location_id]},
    )


def unknown_work_type(name):
    return explain(
        "unknown_work_type",
        "data",
        f"Вид работ «{name}» не найден в справочнике",
        observed={"work_type": name},
    )


def requirements_not_configured(work_type):
    return explain(
        "work_requirements_not_configured",
        "data",
        f"Для вида работ «{work_type['name']}» не настроены требования планирования",
        ids={"work_type_ids": [work_type["id"]]},
    )


def invalid_duration(duration, source, work_type):
    return explain(
        "invalid_service_duration",
        "data",
        f"Недопустимая длительность обслуживания: {duration} мин",
        ids={"work_type_ids": [work_type["id"]]},
        observed={"duration_minutes": duration, "duration_source": source},
        required={"min_minutes": 1, "max_minutes": 2880},
    )


def outside_horizon(window_start, window_end, day_start, horizon_end, day):
    return explain(
        "outside_shift_horizon",
        "time",
        f"Окно визита {clock(window_start, day)}–{clock(window_end, day)} не пересекается"
        f" с днём расчёта: с {clock(day_start, day)} до конца последней смены"
        f" {clock(horizon_end, day)}",
        constraint="visit_window=service_start_in_window",
        observed={"window_start": iso(window_start), "window_end": iso(window_end)},
        required={"from": iso(day_start), "to": iso(horizon_end)},
    )


def equipment_not_reserved(missing, names):
    parts = ", ".join(
        f"«{names.get(a, f'№{a}')}» {reserved} из {required}" for a, reserved, required in missing
    )
    return explain(
        "equipment_not_reserved",
        "inventory",
        f"Не зарезервировано оборудование: {parts}",
        constraint="equipment=office_stock_and_ticket_reservations",
        ids={"appliance_ids": [a for a, _, _ in missing]},
        observed={"appliances": [{"appliance_id": a, "quantity": q} for a, q, _ in missing]},
        required={"appliances": [{"appliance_id": a, "quantity": q} for a, _, q in missing]},
    )


def stock_inconsistent(items, names):
    parts = []
    for item in items:
        name = names.get(item["appliance_id"], f"№{item['appliance_id']}")
        if not item["is_active"]:
            parts.append(f"«{name}» выведено из использования")
        else:
            parts.append(
                f"«{name}» в офисе №{item['office_id']}: резерв {item['reserved']},"
                f" остаток {item['stock']}"
            )
    return explain(
        "stock_inconsistent",
        "inventory",
        "Резерв оборудования нельзя выдать: " + "; ".join(parts),
        constraint="equipment=office_stock_and_ticket_reservations",
        ids={
            "appliance_ids": [i["appliance_id"] for i in items],
            "office_ids": [i["office_id"] for i in items],
        },
        observed={"items": items},
    )


# One engineer against one ticket ---------------------------------------------


def missing_skill(missing, required):
    return explain(
        "missing_skill",
        "skill",
        f"Нет навыка {numbers(missing)}",
        ids={"skill_ids": missing},
        observed={"skill_ids": sorted(set(required) - set(missing))},
        required={"skill_ids": sorted(required)},
    )


def office_mismatch(worker_office, offices):
    return explain(
        "office_mismatch",
        "area",
        f"Оборудование заявки зарезервировано в офисе {numbers(offices)},"
        f" инженер выезжает из офиса №{worker_office}",
        constraint="territory=allocation_office_only_no_service_area",
        ids={"office_ids": offices},
        observed={"office_id": worker_office},
        required={"office_ids": sorted(offices)},
    )


def window_outside_shift(window_start, window_end, shift_start, shift_end, day):
    return explain(
        "window_outside_shift",
        "time",
        f"Окно {clock(window_start, day)}–{clock(window_end, day)} не пересекается"
        f" со сменой {clock(shift_start, day)}–{clock(shift_end, day)}",
        constraint="visit_window=service_start_in_window",
        observed={"shift_start": iso(shift_start), "shift_end": iso(shift_end)},
        required={"window_start": iso(window_start), "window_end": iso(window_end)},
    )


def service_after_shift(earliest_start, duration, shift_end, day):
    finish = earliest_start + timedelta(minutes=duration)
    return explain(
        "service_after_shift_end",
        "time",
        f"Работа {duration} мин при самом раннем начале {clock(earliest_start, day)}"
        f" закончится в {clock(finish, day)}, после конца смены {clock(shift_end, day)}",
        constraint="shift_end=hard_including_return",
        observed={"earliest_service_end": iso(finish)},
        required={"shift_end": iso(shift_end)},
    )


def unreachable(profile, reachable_profiles, location_id):
    if reachable_profiles:
        return explain(
            "unreachable_by_transport",
            "transport",
            f"Провайдер не нашёл маршрута для профиля «{PROFILE[profile]}»; маршрут есть для: "
            + ", ".join(PROFILE[p] for p in reachable_profiles),
            ids={"location_ids": [location_id]},
            observed={"routing_mode": profile},
            required={"routing_modes": reachable_profiles},
        )
    return explain(
        "address_unreachable",
        "unreachable",
        "Провайдер не нашёл дороги между адресом заявки и точкой маршрута инженера",
        ids={"location_ids": [location_id]},
        observed={"routing_mode": profile},
    )


def arrival_after_window(arrival, window_end, day):
    return explain(
        "arrival_after_window",
        "time",
        f"Даже при выезде в начале смены сразу к заявке инженер прибудет в {clock(arrival, day)},"
        f" позже конца окна {clock(window_end, day)}",
        constraint="visit_window=service_start_in_window",
        observed={"earliest_arrival": iso(arrival)},
        required={"window_end": iso(window_end)},
    )


def return_after_shift(finish, shift_end, day):
    return explain(
        "return_after_shift_end",
        "time",
        f"Даже как единственный визит маршрут с дорогой до конечной точки закончится"
        f" в {clock(finish, day)}, после конца смены {clock(shift_end, day)}",
        constraint="shift_end=hard_including_return",
        observed={"earliest_route_end": iso(finish)},
        required={"shift_end": iso(shift_end)},
    )


def route_full(visits):
    return explain(
        "route_full",
        "capacity",
        f"В рассчитанный маршрут инженера ({plural(visits, 'визит', 'визита', 'визитов')})"
        " заявка не помещается ни в одну позицию по времени",
        observed={"planned_visits": visits},
    )


def slot_available(position, after_ticket_id):
    where = "первым визитом" if after_ticket_id is None else f"после заявки №{after_ticket_id}"
    return explain(
        "slot_available",
        "search",
        f"Заявка помещается в рассчитанный маршрут инженера {where}",
        ids={"ticket_ids": [] if after_ticket_id is None else [after_ticket_id]},
        observed={"position": position},
    )


# Why a ticket stays unassigned -----------------------------------------------


def no_available_workers(excluded):
    return explain(
        "no_available_workers",
        "availability",
        f"Нет доступных инженеров: все выбранные ({excluded}) исключены из расчёта",
        observed={"excluded_workers": excluded},
    )


def skill_nobody_has(missing, required, checked):
    return explain(
        "missing_skill",
        "skill",
        f"Ни у одного из выбранных инженеров ({checked}) нет навыка {numbers(missing)}",
        ids={"skill_ids": missing},
        required={"skill_ids": sorted(required)},
    )


def no_eligible_worker(candidates):
    codes = Counter(c["reason"]["code"] for c in candidates)
    categories = {c["reason"]["category"] for c in candidates}
    worker_ids = [c["worker_id"] for c in candidates]
    if len(codes) == 1:
        code = next(iter(codes))
        summary = f"у всех: {LABELS.get(code, code)}"
    else:
        code = "no_eligible_worker"
        summary = ", ".join(f"{LABELS.get(k, k)} — {n}" for k, n in sorted(codes.items()))
    return explain(
        code,
        categories.pop() if len(categories) == 1 else "mixed",
        f"Не подходит ни один из {genitive(len(candidates), 'инженера', 'инженеров')}: {summary}",
        ids={"worker_ids": worker_ids},
        observed={"by_code": dict(sorted(codes.items()))},
    )


def feasible_slot_missed(worker_ids, limit_seconds):
    return explain(
        "feasible_slot_missed",
        "search",
        f"Проверка нашла допустимое место у {numbers(worker_ids)}, но решатель не выбрал его"
        f" за лимит поиска {limit_seconds} с",
        constraint="search_time_limit_seconds",
        ids={"worker_ids": worker_ids},
        observed={"search_time_limit_seconds": limit_seconds},
    )


def no_slot_in_plan(worker_ids):
    return explain(
        "no_slot_in_computed_plan",
        "capacity",
        f"Не найдено подходящее место в рассчитанном плане: маршруты подходящих инженеров"
        f" ({numbers(worker_ids)}) заполнены. Полная перестановка маршрутов не проверялась,"
        " это не доказательство невозможности",
        ids={"worker_ids": worker_ids},
    )


# Factors of a planned visit --------------------------------------------------


def skills_factor(required):
    if not required:
        return explain("no_skills_required", "skill", "Для вида работ навыки не требуются")
    return explain(
        "skills_match",
        "skill",
        f"Навыки подходят: у инженера есть все требуемые ({numbers(required)})",
        ids={"skill_ids": required},
        required={"skill_ids": sorted(required)},
    )


def transport_factor(transport_type, profile, minutes, first):
    source = "от офиса" if first else "от предыдущей заявки"
    note = ", оценка без расписания" if profile == "approximated_transit" else ""
    return explain(
        "transport",
        "transport",
        f"{TRANSPORT.get(transport_type, transport_type).capitalize()}: {minutes} мин в пути"
        f" {source}{note}",
        observed={
            "transport_type": transport_type,
            "routing_mode": profile,
            "travel_minutes": minutes,
        },
    )


def window_factor(start, window_start, window_end, waiting, day):
    wait = f", ожидание {waiting} мин" if waiting else ""
    return explain(
        "start_in_window",
        "time",
        f"Начало в {clock(start, day)} внутри окна {clock(window_start, day)}–"
        f"{clock(window_end, day)}{wait}",
        constraint="visit_window=service_start_in_window",
        observed={"service_start_at": iso(start), "waiting_minutes": waiting},
        required={"window_start": iso(window_start), "window_end": iso(window_end)},
    )


def equipment_factor(allocations, names):
    if not allocations:
        return explain("no_equipment_required", "inventory", "Оборудование для заявки не требуется")
    parts = ", ".join(
        f"«{names.get(a['appliance_id'], '№' + str(a['appliance_id']))}» × {a['quantity']}"
        for a in allocations
    )
    offices = sorted({a["office_id"] for a in allocations})
    return explain(
        "equipment_reserved",
        "inventory",
        f"Комплект зарезервирован в офисе {numbers(offices)}: {parts}",
        constraint="equipment=office_stock_and_ticket_reservations",
        ids={"appliance_ids": [a["appliance_id"] for a in allocations], "office_ids": offices},
        observed={"appliances": allocations},
    )


def priority_factor(priority):
    return explain(
        "equal_priority",
        "policy",
        "Приоритеты не применяются: действующая политика считает все заявки равноценными",
        constraint=f"priority={priority}",
    )


def selection_factor(candidates, objective_order):
    if candidates == 1:
        return explain(
            "only_eligible_worker",
            "selection",
            "Единственный инженер, прошедший проверку навыков, офиса и смены",
            observed={"eligible_workers": 1},
        )
    goal = ", затем ".join(OBJECTIVE.get(item, item) for item in objective_order)
    return explain(
        "selected_by_plan_objective",
        "selection",
        f"Проверку прошли {engineers(candidates)}; назначение выбрано по общей цели плана"
        f" ({goal}), без отдельного сравнения инженеров для этой заявки",
        observed={"eligible_workers": candidates},
    )


def resource_message(workers, covered, considered, complete):
    tickets = f"{genitive(considered, 'заявки', 'заявок')} без места"
    if not workers:
        text = f"Оценка: копии доступных инженеров не размещают ни одну из {tickets}."
    else:
        like = ", ".join(
            f"№{w} × {n}" for w, n in sorted(Counter(x["like_worker_id"] for x in workers).items())
        )
        count = len(workers)
        verb = "разместил" if count % 10 == 1 and count % 100 != 11 else "разместили"
        text = (
            f"Оценка: ещё {engineers(count)} с навыками, офисом, сменой и транспортом"
            f" как у {like} {verb} бы {covered} из {tickets}."
        )
    text += " Это жадная оценка, а не доказанный минимальный штат."
    if not complete:
        text += " Расчёт остановлен по лимиту проверок, оценка неполная."
    return text
