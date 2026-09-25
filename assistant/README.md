# Ассистент (чат для адаптации сотрудников)

Отдельный stateless-сервис на FastAPI. Отвечает исполнителям, начальникам бригад
и диспетчерам на вопросы о работе в системе, о конкретной заявке, о смене и о типовых
работах. Модель — малая LLM в Ollama; факты берутся из базы знаний в Markdown и из
контекста, который передаёт основной бэкенд. В БД сервис не ходит.

## Как это работает

1. Бэкенд проверяет JWT, определяет роль пользователя и собирает контекст: профиль,
   открытую заявку с комментариями, заявки на день.
2. Бэкенд вызывает `POST /api/v1/chat` этого сервиса.
3. Сервис ищет по базе знаний (`knowledge/`) разделы, доступные роли (BM25 со
   стеммингом русского языка). Разделы по типу работ открытой заявки поднимаются выше.
4. Системный промпт с правилами роли, найденные разделы, контекст и вопрос уходят
   в Ollama (`/api/chat`, без режима рассуждений).

Авторизации в самом сервисе нет: наружу его не публикуем, вызывает только бэкенд.

## API

`POST /api/v1/chat`

```json
{
  "role": "worker",
  "message": "Почему мою заявку перенесли?",
  "history": [
    {"role": "user", "content": "Привет"},
    {"role": "assistant", "content": "Здравствуйте! Чем помочь?"}
  ],
  "context": {
    "user": {"name": "Иван Иванов", "workshift_start": "08:00", "workshift_end": "17:00",
             "skills": ["Монтаж ВОЛС"], "brigade": "Бригада Приморского района"},
    "ticket": {
      "id": 104, "title": "Заменить маршрутизатор", "work_type": "Замена оборудования",
      "status": "planned", "address": "Санкт-Петербург, Невский район, ...",
      "visit_window_start": "2026-09-18T14:00:00+03:00",
      "visit_window_end": "2026-09-18T18:00:00+03:00",
      "planned_start_at": "2026-09-18T15:00:00+03:00",
      "planned_end_at": "2026-09-18T16:00:00+03:00",
      "comments": [{"author": "Система", "created_at": "2026-09-17T08:40:00+03:00",
                    "text": "Заявка перенесена ... Причина: ..."}]
    },
    "tickets": []
  }
}
```

- `role` — `worker`, `foreman` или `observer`, берётся из токена на бэкенде.
- `history` — до 10 последних сообщений; сервис историю не хранит.
- `context` и все его поля необязательны. Полная схема — в Swagger:
  `http://127.0.0.1:8002/docs`. Даты передавайте с часовым поясом: сервис показывает
  время в том поясе, в котором его получил.
- Причины переносов модель объясняет по комментариям заявки, поэтому планировщику
  стоит писать их комментарием от автора «Система».

Ответ:

```json
{"answer": "...", "sources": [{"title": "Планирование маршрутов и переносы",
 "section": "Почему заявку перенесли или переназначили"}], "model": "qwen3.5:0.8b"}
```

`503` — Ollama недоступна или модель не загружена.

## База знаний

Формат файлов и правила — в [`knowledge/README.md`](knowledge/README.md).
Для нового типа работ достаточно добавить Markdown-файл с `work_type`, совпадающим
с `tickets.work_type`, — перезапуск сервиса подхватит его.

## Запуск

В Docker вместе со всеми сервисами (Ollama и скачивание модели поднимутся сами):

```bash
docker compose up --build assistant
```

На машине с видеокартой NVIDIA:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

Локально (Ollama должна слушать `http://localhost:11434`):

```bash
cd assistant
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/uvicorn app.main:app --reload --port 8002
```

Переменные: `OLLAMA_URL`, `ASSISTANT_MODEL`, `LLM_TEMPERATURE`, `LLM_NUM_CTX`,
`LLM_MAX_TOKENS`, `LLM_NUM_THREAD`, `RETRIEVAL_TOP_K` (см. `app/core/config.py`).

## Проверки

```bash
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m unittest discover -s tests -t .
```

`requirements.lock` фиксирует точные версии и хеши пакетов для Python 3.12.13; Docker
и GitHub Actions ставят тот же набор.

## Сравнение моделей

`eval/questions.yaml` — вопросы по ролям с ожидаемыми фактами, `eval/contexts.yaml` —
контексты заявок и смен. Прогон идёт тем же кодом, что и сервис:

```bash
.venv/bin/python -m eval.run_bench --retrieval-only
.venv/bin/python -m eval.run_bench --models qwen3.5:0.8b qwen3:0.6b
```

Отчёт с метриками и всеми ответами пишется в `eval/results/<время>/report.md`.
Автоматический балл — грубая проверка по ключевым словам; ответы нужно читать.
Итоги сравнения Qwen3.5-0.8B и Qwen3-0.6B — в [`eval/RESULTS.md`](eval/RESULTS.md).
