# Планирование выездных работ

Проект для диспетчера инженерной службы: заявки, сотрудники и их навыки,
адреса, бригады, оборудование и сохранённые маршруты. Основной API работает
на FastAPI/PostgreSQL. Отдельный `planner` решает VRPTW через OR-Tools.
`frontend` пока содержит стартовый интерфейс Next.js.

## Где искать код

| Каталог | Назначение |
| --- | --- |
| [backend](backend/README.md) | HTTP API, бизнес-правила, авторизация, миграции |
| [backend/app/modules](backend/app/modules/README.md) | Предметные модули и объяснения соседних файлов |
| [planner](planner/README.md) | Расчёт маршрутов по готовым матрицам времени |
| [frontend](frontend/README.md) | Next.js; пока шаблон, интеграция интерфейса впереди |
| [data/synthetic](data/synthetic/README.md) | Готовые CSV/XLSX: 1 500 и 10 000 заявок |
| [backend/bruno](backend/bruno/README.md) | Последовательные API-сценарии |
| [.github/workflows](.github/workflows/README.md) | Автоматические проверки |
| [docs](docs/README.md) | Контракты, решения, аудит и ограничения |

Зависимости между компонентами:

```text
Клиент / Swagger / Bruno -> backend -> PostgreSQL
Клиент расчёта           -> planner -> OR-Tools
```

Планировщик пока не вызывается автоматически из backend. Сохранить уже построенный
план можно через `POST /api/v1/routes` или `/routes/batch`, передав инженера, дату,
упорядоченные точки с временем прибытия и, при наличии, готовую линию маршрута.
Алгоритм оптимизации и существующие операции с заявками эта операция не изменяет.

## Запуск

Нужны Python 3.12+, PostgreSQL 16+ и Node.js 22 для frontend/Bruno.
Полный запуск через Docker описан в [DOCKER.md](DOCKER.md).
Docker Compose автоматически применяет миграции backend при запуске контейнера.

Локальный backend, PowerShell, из корня проекта:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# В .env укажите DATABASE_URL и собственный JWT_SECRET_KEY.
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Swagger: `http://127.0.0.1:8000/docs`. `/health` проверяет процесс, а не доступность БД.
На Linux/macOS используется `.venv/bin/python` вместо `.venv\Scripts\python`.
Первый демонстрационный диспетчер создаётся командой `python seed_demo.py`
в отдельной локальной демонстрационной БД; учётные данные описаны в backend README.

```powershell
cd ../frontend
npm ci
npm run dev
```

Для planner создайте отдельное окружение, установите `planner/requirements.txt`
и запустите из `planner`: `python -m uvicorn app.main:app --port 8001`.

## Три дополнения

1. **Обмен всеми предметными данными.** `GET /api/v1/data/export?format=xlsx`
   возвращает книгу из 21 предметного листа; `format=csv` — ZIP с CSV для каждой
   таблицы. Импорт: `POST /api/v1/data/import`, файл в multipart-поле `file`.
   По умолчанию выполняется только проверка (`dry_run=true`). Запись включается
   параметром `dry_run=false`. Подробности — [контракт обмена](docs/DATA_EXCHANGE.md).
2. **История маршрутов.** Снимки GeoJSON с `route_number`, отдельным от ID;
   нумерация в пределах инженера и даты, времена прибытия и порядок каждой точки.
   Подробности — [модуль routes](backend/app/modules/routes/README.md).
3. **Транспорт.** В `worker_profile.transport_type` доступны `car`, `walking`,
   `bicycle`, `public_transport`. Старые записи и запросы без поля используют
   `walking`; PATCH без этого поля сохраняет прежнее значение.

Полная выгрузка доступна только `observer`. Пароли, refresh-токены, push-токены и
служебные квитанции импорта не экспортируются. Это перенос предметных данных,
не побайтовая резервная копия PostgreSQL. Для резервной копии нужен `pg_dump`.

## Проверки

Создайте отдельную БД с именем, заканчивающимся на `_test`. Для кириллицы нужна
локаль с поддержкой регистронезависимого сравнения: например `ru-RU` через ICU
или обычная UTF-8 локаль контейнера PostgreSQL. Локаль `C` без Unicode case folding
не подходит существующим тестам справочников.

Из `backend` в PowerShell:

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://beeline_test:beeline_test@127.0.0.1:5432/beeline_test'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
$env:JWT_SECRET_KEY='isolated-tests-only-key-at-least-32-characters'
$env:NOTIFICATION_DISPATCHER_ENABLED='false'
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
```

Тесты БД используют случайные схемы и удаляют только собственные схемы. Без
`TEST_DATABASE_URL` интеграционные тесты пропускаются: это не считается полным прогоном.
Как запускать всю коллекцию на чистой тестовой БД — [Bruno README](backend/bruno/README.md).

```powershell
# Из frontend
npm run lint
npm run build
# Из planner, в его окружении
python -m unittest discover -s tests -p test_api_contract.py -v
```

## Синтетические данные

Готовые наборы уже находятся в [data/synthetic](data/synthetic/README.md).
Генератор не подключается к БД:

```powershell
# Из backend
python generate_synthetic.py --output ../data/synthetic/standard
python generate_synthetic.py --output .local/custom --seed 84 --tickets 10000 --workers 240 --days 14
python seed_synthetic.py --seed 42
```

Последняя команда использует **только** `TEST_DATABASE_URL` и схему `synthetic_42`.
Повторный запуск возвращает квитанцию без дублирования. `--reset` очищает только
эту синтетическую схему; команда откажется работать с БД, имя которой не заканчивается
на `_test`. Не направляйте приложение на рабочую БД для прогона Bruno.

Оставшиеся ограничения существующей системы перечислены в
[аудите](docs/AUDIT_2026-09-18.md). Изменения вне трёх порученных задач не вносились.
