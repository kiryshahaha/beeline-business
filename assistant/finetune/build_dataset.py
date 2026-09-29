"""Build the chat fine-tuning set for the assistant model (mlx-lm `messages` JSONL).

Every example is rendered by the service's own prompt code: the same system rules, the
same retrieved «Справка» and the same context block, so the model learns exactly the
format it sees in production. Three sources:

1. knowledge-base answers written per section (`kb_qa.yaml`);
2. questions about the day on contexts built from the synthetic dataset shape — the
   reference answers come from `facts.py`, so they are exact;
3. questions outside the knowledge base, answered with an honest «Не знаю».

Questions close to the eval set (`eval/questions.yaml`, including held-out `h-*`) are
dropped so the evaluation stays honest.

    python -m finetune.build_dataset --synthetic ../data/synthetic/standard/dataset.zip \
        --out ~/Downloads/beeline-business/finetune/data
"""

import argparse
import csv
import io
import json
import random
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.modules.chat.facts import BUILDERS, Facts, normalize
from app.modules.chat.knowledge import KnowledgeBase, tokenize
from app.modules.chat.prompts import ESCALATION, build_messages
from app.modules.chat.schemas import ChatContext, ChatRequest
from app.modules.chat.service import retrieve

HERE = Path(__file__).resolve().parent
EVAL_DIR = HERE.parent / "eval"
MOSCOW = timezone(timedelta(hours=3))
NEAR_DUPLICATE = 0.6

# Fictional people; streets are real streets of the «Восток» area of Moscow.
FIRST_NAMES = ["Иван", "Пётр", "Алексей", "Сергей", "Дмитрий", "Никита", "Олег", "Максим"]
SURNAMES = ["Иванов", "Соколов", "Кузнецов", "Смирнов", "Орлов", "Лебедев", "Морозов", "Волков"]
STREETS = [
    "Люблинская улица",
    "Таганская улица",
    "Рязанский проспект",
    "Волгоградский проспект",
    "Нижегородская улица",
    "улица Юных Ленинцев",
    "Ферганская улица",
    "Авиамоторная улица",
    "шоссе Энтузиастов",
    "улица Михайлова",
]
TITLES = {
    "emergency": ["Обрыв оптики на ТКД", "Нет связи у группы абонентов", "Авария на узле доступа"],
    "connection": ["Подключить квартиру", "Протянуть оптику до кросса", "Новое подключение"],
    "repair": ["Проверить кабель", "Настроить Wi-Fi", "Низкая скорость интернета"],
    "additional": ["Доставить второй роутер", "Установить ТВ-приставку", "Заменить ONT-терминал"],
}
WORK_TYPES = {
    "emergency": "Аварий на ТКД",
    "connection": "Подключение клиентов Базовая",
    "repair": "Локальная заявка/ремонт у клиента",
    "additional": "Дозаказ оборудования",
}
NORM_MINUTES = {"emergency": 100, "connection": 90, "repair": 50, "additional": 40}
APPLIANCES = {
    "emergency": [("Оптический патч-корд", 2)],
    "connection": [("ONT-терминал", 1), ("Оптический патч-корд", 1)],
    "repair": [("Маршрутизатор Wi-Fi 6", 1)],
    "additional": [("Точка доступа Wi-Fi", 1)],
}
REASONS = [
    ("emergency_inserted", "Поступила аварийная заявка №{n}, маршрут пересчитан"),
    ("worker_unavailable_other", "Исполнитель {name} стал недоступен, его заявки перераспределены"),
    ("previous_delay", "Предыдущая работа задерживается до {time}"),
    ("window_changed", "Клиент попросил другое окно визита"),
    ("manual_edit", "Изменено диспетчером"),
]

# Question wordings per data intent. Many are deliberately unlike the regex patterns:
# at runtime such questions fall through to the model together with the context.
DATA_QUESTIONS = {
    "shift": [
        "до которого часа я сегодня?",
        "напомни мою смену",
        "я сегодня с какого по какое?",
        "во сколько мне сегодня заканчивать",
        "какое у меня рабочее время сегодня",
    ],
    "day_count": [
        "сколько вызовов сегодня",
        "много мне ещё ехать по заявкам?",
        "сколько адресов осталось",
        "какой у меня объём на сегодня",
        "сколько уже закрыл и сколько впереди",
    ],
    "next_ticket": [
        "а потом куда?",
        "что следующее по плану",
        "куда мне после текущей",
        "где я должен быть после этой заявки",
        "какой следующий адрес",
    ],
    "current_ticket": [
        "на какой я сейчас",
        "какую заявку я сейчас делаю",
        "что сейчас у меня в работе",
    ],
    "ticket_time": [
        "к которому часу к клиенту на следующую?",
        "во сколько меня ждут на следующей заявке",
        "когда начинается следующая заявка",
    ],
    "ticket_address": [
        "какой адрес у следующей",
        "куда ехать на следующую заявку",
        "подъезд и квартира на следующей какие",
    ],
    "day_list": [
        "распиши мой день",
        "какие заявки у меня сегодня",
        "что мне осталось сделать сегодня",
        "перечисли заявки по порядку",
    ],
    "why_changed": [
        "что случилось со следующей заявкой, почему время другое?",
        "почему следующую заявку сдвинули",
        "почему поменялось время по следующей заявке",
    ],
    "ticket_equipment": [
        "что брать на следующую",
        "какое оборудование на следующую заявку",
    ],
}

OUT_OF_SCOPE = [
    "Какая у нас зарплата в этом месяце?",
    "Когда будет отпуск?",
    "Сколько стоит подключение для клиента?",
    "Какой тариф посоветовать клиенту?",
    "Какая завтра погода?",
    "Как починить машину, если она не заводится?",
    "Сколько платят за ночную смену?",
    "Где ближайшая столовая?",
    "Когда выдадут новую форму?",
    "Какой пароль от корпоративного Wi-Fi в офисе?",
    "Как оформить больничный?",
    "Можно ли взять отгул завтра?",
    "Кто мой начальник по штатному расписанию?",
    "Как настроить умный дом клиента?",
    "Сколько гигабайт в тарифе у клиента?",
    "Как сменить номер телефона клиенту?",
    "Какие акции сейчас у оператора?",
    "Как вернуть деньги клиенту за услугу?",
    "Какой антивирус поставить клиенту на ноутбук?",
    "Как подключить клиенту мобильную связь?",
    "Сколько стоит ONT-терминал, если клиент хочет купить?",
    "Кто победил вчера в футболе?",
    "Расскажи анекдот",
    "Как настроить принтер клиента?",
    "Можно ли продать клиенту свой старый роутер?",
    "Где оплатить штраф за парковку служебной машины?",
    "Какой график работы у офиса продаж?",
    "Как стать бригадиром?",
    "Сколько заявок нужно закрыть для премии?",
    "Как записаться на обучение по сварке оптики?",
]


def near_duplicate(question: str, others: list[set[str]]) -> bool:
    stems = set(tokenize(question))
    if not stems:
        return False
    return any(len(stems & other) / len(stems | other) > NEAR_DUPLICATE for other in others)


def eval_questions() -> list[set[str]]:
    cases = yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))
    return [set(tokenize(case["question"])) for case in cases]


def example(request: ChatRequest, answer: str, chunks) -> dict:
    messages = build_messages(request, chunks)
    messages.append({"role": "assistant", "content": answer})
    return {"messages": messages}


# --- 1. Knowledge base answers ---


def knowledge_examples(knowledge: KnowledgeBase, rng: random.Random, blocked) -> list[dict]:
    by_key = {f"{chunk.path}#{chunk.section}": chunk for chunk in knowledge.chunks}
    top_k = get_settings().retrieval_top_k
    items = yaml.safe_load((HERE / "kb_qa.yaml").read_text(encoding="utf-8"))
    examples, skipped = [], 0
    for item in items:
        target = by_key[item["section"]]
        for pair in item["qa"]:
            if near_duplicate(pair["q"], blocked):
                skipped += 1
                continue
            roles = [role for role in item["roles"] if role in target.roles]
            for role in rng.sample(roles, k=min(len(roles), 2)):
                request = ChatRequest(role=role, message=pair["q"])
                chunks = retrieve(request, knowledge, top_k)
                if target not in chunks:
                    chunks = [target, *chunks[: top_k - 1]]
                examples.append(example(request, pair["a"], chunks))
    print(f"knowledge: {len(examples)} examples, {skipped} questions dropped as close to eval")
    return examples


# --- 2. Questions about the day on synthetic-shaped contexts ---


def synthetic_shifts(zip_path: Path) -> list[tuple[str, str]]:
    with zipfile.ZipFile(zip_path) as archive:
        text = archive.read("workers.csv").decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text))
    return sorted({(r["workshift_start"][:5], r["workshift_end"][:5]) for r in rows})


def _at(day: date, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MOSCOW)


def day_context(rng: random.Random, shift: tuple[str, str], index: int) -> dict:
    day = date(2026, 9, 21) + timedelta(days=index % 14)
    start = _at(day, shift[0])
    end = _at(day, shift[1])
    if end <= start:
        end += timedelta(days=1)
    name = rng.choice(FIRST_NAMES)
    count = rng.randint(3, 7)
    cursor = start + timedelta(minutes=rng.choice([20, 30, 40]))
    done = rng.randint(0, count - 1)
    tickets = []
    for position in range(count):
        category = rng.choices(
            ["repair", "connection", "emergency", "additional"], weights=[4, 4, 1, 1]
        )[0]
        minutes = NORM_MINUTES[category]
        arrival = cursor
        work_start = arrival + timedelta(minutes=10)
        work_end = work_start + timedelta(minutes=minutes - 20)
        window_start = arrival - timedelta(minutes=rng.choice([0, 30, 60]))
        if position < done:
            state = "completed"
        elif position == done:
            state = rng.choice(["in_progress", "en_route", "dispatched"])
        else:
            state = rng.choice(["dispatched", "assigned"])
        street = rng.choice(STREETS)
        ticket = {
            "id": 1000 + index * 10 + position,
            "sequence": position + 1,
            "title": rng.choice(TITLES[category]),
            "category": category,
            "work_type": WORK_TYPES[category],
            "state": state,
            "visit_window_start": window_start.isoformat(),
            "visit_window_end": (window_start + timedelta(hours=3)).isoformat(),
            "planned_arrival_at": arrival.isoformat(),
            "planned_start_at": work_start.isoformat(),
            "planned_end_at": work_end.isoformat(),
            "required_appliances": [
                {"appliance_name": a, "quantity": q, "unit": "шт"} for a, q in APPLIANCES[category]
            ],
            "location": {
                "street": street,
                "address": f"Москва, Восток, {street}, д. {rng.randint(1, 60)}, "
                f"подъезд {rng.randint(1, 6)}, этаж {rng.randint(1, 16)}, "
                f"кв./пом. {rng.randint(1, 300)}",
            },
        }
        if state == "completed" and rng.random() < 0.4:
            ticket["completion_review"] = {"state": rng.choice(["pending", "confirmed"])}
        if position > done and rng.random() < 0.5:
            code, template = rng.choice(REASONS)
            moved_from = work_start - timedelta(minutes=rng.choice([30, 40, 60, 90]))
            ticket["last_change"] = {
                "at": (start + timedelta(minutes=rng.randint(30, 120))).isoformat(),
                "kind": "rescheduled",
                "source": "planner",
                "fields": {
                    "planned_start_at": {
                        "from": moved_from.isoformat(),
                        "to": work_start.isoformat(),
                    }
                },
                "reason_code": code,
                "reason_text": template.format(
                    n=rng.randint(100, 999),
                    name=f"{rng.choice(FIRST_NAMES)} {rng.choice(SURNAMES)}",
                    time=(work_start - timedelta(minutes=15)).strftime("%H:%M"),
                ),
            }
        tickets.append(ticket)
        cursor = work_end + timedelta(minutes=rng.choice([20, 30, 40]))
    current = next((t for t in tickets if t["state"] in {"in_progress", "en_route"}), None)
    upcoming = [t for t in tickets if t["state"] in {"assigned", "dispatched"}]
    states = [t["state"] for t in tickets]
    context = {
        "day": {
            "date": day.isoformat(),
            "worker": {"name": name, "surname": rng.choice(SURNAMES)},
            "shift": {"is_working_day": True, "start": start.isoformat(), "end": end.isoformat()},
            "day_state": {"available": True, "current_ticket_id": current and current["id"]},
            "summary": {
                "total": count,
                "completed": states.count("completed"),
                "awaiting_confirmation": sum(
                    1 for t in tickets if t.get("completion_review", {}).get("state") == "pending"
                ),
                "in_progress": states.count("in_progress"),
                "remaining": sum(s in {"assigned", "dispatched", "en_route"} for s in states),
                "cancelled": 0,
            },
            "current_ticket_id": current and current["id"],
            "next_ticket_id": upcoming[0]["id"] if upcoming else None,
            "tickets": tickets,
        },
        "tomorrow_shift": {"is_working_day": rng.random() < 0.7},
    }
    if context["tomorrow_shift"]["is_working_day"]:
        tomorrow = day + timedelta(days=1)
        context["tomorrow_shift"].update(start=_at(tomorrow, shift[0]).isoformat())
        tomorrow_end = _at(tomorrow, shift[1])
        if tomorrow_end <= _at(tomorrow, shift[0]):
            tomorrow_end += timedelta(days=1)
        context["tomorrow_shift"]["end"] = tomorrow_end.isoformat()
    return context


def data_examples(
    knowledge: KnowledgeBase, rng: random.Random, shifts, blocked, contexts: int
) -> list[dict]:
    top_k = get_settings().retrieval_top_k
    examples = []
    for index in range(contexts):
        context = ChatContext.model_validate(day_context(rng, rng.choice(shifts), index))
        for intent in rng.sample(list(DATA_QUESTIONS), k=4):
            question = rng.choice(DATA_QUESTIONS[intent])
            if near_duplicate(question, blocked):
                continue
            request = ChatRequest(role="worker", message=question, context=context)
            fact = BUILDERS[intent](Facts(request), normalize(question))
            if fact is None:
                continue
            examples.append(example(request, fact.text, retrieve(request, knowledge, top_k)))
    print(f"data: {len(examples)} examples on {contexts} synthetic days")
    return examples


# --- 3. Outside the knowledge base ---


def out_of_scope_examples(knowledge: KnowledgeBase, rng: random.Random, blocked) -> list[dict]:
    top_k = get_settings().retrieval_top_k
    examples = []
    for question in OUT_OF_SCOPE:
        if near_duplicate(question, blocked):
            continue
        for role in rng.sample(["worker", "foreman", "observer"], k=2):
            request = ChatRequest(role=role, message=question)
            answer = f"Не знаю — {ESCALATION[role]}."
            examples.append(example(request, answer, retrieve(request, knowledge, top_k)))
    print(f"out of scope: {len(examples)} examples")
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--contexts", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    knowledge = KnowledgeBase.from_dir(get_settings().knowledge_dir)
    blocked = eval_questions()
    examples = (
        knowledge_examples(knowledge, rng, blocked)
        + data_examples(knowledge, rng, synthetic_shifts(args.synthetic), blocked, args.contexts)
        + out_of_scope_examples(knowledge, rng, blocked)
    )

    # Split by question: the same question asked for two roles must not land in both
    # parts, otherwise validation loss looks better than generalisation really is.
    def question(row: dict) -> str:
        return row["messages"][-2]["content"].rsplit("Вопрос: ", 1)[-1]

    questions = sorted({question(row) for row in examples})
    rng.shuffle(questions)
    held = set(questions[: max(5, len(questions) // 10)])
    valid = [row for row in examples if question(row) in held]
    train = [row for row in examples if question(row) not in held]
    rng.shuffle(train)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, part in (("valid", valid), ("train", train)):
        with (args.out / f"{name}.jsonl").open("w", encoding="utf-8") as file:
            for row in part:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"train: {len(train)}, valid: {len(valid)} → {args.out}")


if __name__ == "__main__":
    main()
