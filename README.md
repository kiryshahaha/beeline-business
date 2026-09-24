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
                        -> planner -> OR-Tools
                        -> Geoapify (матрицы и дороги)
```

Backend вызывает существующий /api/v1/solve через модуль planning: preview рассчитывает
предложение, apply одной транзакцией сохраняет назначения, расписание и GeoJSON.
Цель — выполнить больше заявок в сменах, затем сократить время в пути.
[Контракт и ограничения](backend/app/modules/planning/README.md).
Ручное сохранение ранее построенных маршрутов через /api/v1/routes остаётся доступным.

## Запуск

Поддерживаемые версии и чистые команды запуска backend с planner собраны
в [руководстве runtime](docs/RUNTIME.md). Compose запускает PostgreSQL 17,
применяет миграции перед backend и проверяет `/ready`; для локальной демонстрации
не нужны Firebase credentials или ключ Geoapify.

## Три дополнения

1. **Обмен всеми предметными данными.** `GET /api/v1/data/export?format=xlsx`
   возвращает книгу из 25 предметных листов; `format=csv` — ZIP с CSV для каждой
   таблицы. Импорт: `POST /api/v1/data/import`, файл в multipart-поле `file`.
   По умолчанию выполняется только проверка (`dry_run=true`). Запись включается
   параметром `dry_run=false`. Подробности — [контракт обмена](docs/DATA_EXCHANGE.md).
2. **История маршрутов.** Снимки GeoJSON с `route_number`, отдельным от ID;
   нумерация в пределах инженера и даты, времена прибытия и порядок каждой точки.
   Подробности — [модуль routing](backend/app/modules/routing/README.md).
3. **Транспорт.** В `worker_profile.transport_type` доступны `car`, `walking`,
   `bicycle`, `public_transport`. Старые записи и запросы без поля используют
   `walking`; PATCH без этого поля сохраняет прежнее значение.

Полная выгрузка доступна только `observer`. Пароли, refresh-токены, push-токены и
служебные квитанции импорта не экспортируются. Это перенос предметных данных,
не побайтовая резервная копия PostgreSQL. Для резервной копии нужен `pg_dump`.

## Проверки

Backend CI использует Python 3.12, PostgreSQL 17, Node 24 для Bruno и хешированные
lock-файлы. Он запускает backend unittest, проверку seed/синтетических данных и
Bruno E2E с настоящим planner. Подробный запуск и команды обновления lock-файлов
описаны в [руководстве runtime](docs/RUNTIME.md); Bruno сценарии — в
[backend/bruno](backend/bruno/README.md).

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
