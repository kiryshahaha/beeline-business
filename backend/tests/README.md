# Проверки backend

Из backend: `python -m unittest discover -s tests -v`.
Нужны установленные requirements и TEST_DATABASE_URL на отдельную PostgreSQL БД
с именем `*_test`. Без переменной интеграционные классы завершаются ошибкой; обязательные проверки не пропускаются.

`support.py` создаёт случайную схему для каждого интеграционного класса,
применяет/откатывает миграции и сверяет metadata через Alembic. Обычные тесты
используют откат транзакции; проверки реальных коммитов очищают только свою схему.

| Группа | Что проверяет |
| --- | --- |
| `test_data_formats.py` | CSV/XLSX, все таблицы, типы, формулы, ошибочные файлы, воспроизводимость |
| `test_exchange_and_routes_api.py` | Реальная БД/API: атомарность, повторный импорт, роли, склад, транспорт, GeoJSON, конкурентные номера |
| `test_exchange_roundtrip_and_migration.py` | Перенос между независимыми схемами с другими ID, HTTP-выгрузки, обновление схемы 0008 |
| `test_users_and_auth_api.py`, `test_auth_security.py` | Пользователи, роли, JWT и пароли |
| `test_tickets*`, `test_ticket_*` | Заявки, назначения, статусы, комментарии и транзакции |
| `test_brigades*`, `test_brigade_*`, `test_offices_api.py` | Организация и видимость |
| `test_appliances_api.py` | Номенклатура и склад |
| `test_analytics_*` | Сводка заявок, загруженность бригад и лента последних действий |
| `test_schedule_api.py` | Интервалы смен, включая ночные, заявки на сутки, фильтр офиса и доступ ролей |
| `test_notifications*`, `test_firebase_gateway.py` | Очередь, WebSocket, токены и граница SDK Firebase |
| `test_calendar_feed_api.py` | Файл iCalendar, хранение хеша токена, перевыпуск, отзыв и роли |
| `test_worker_line_status_api.py` | Снятие и возврат инженера, освобождение `planned`, транзакция, роли, миграция и планирование |
| `test_database.py`, `test_locations_api.py`, `test_*migration.py` | Ограничения БД и миграции |
| `test_seed_demo.py`, `test_openapi.py`, `test_enum_types.py`, `test_health.py` | Демонстрационные данные и публичные контракты |

Файловые тесты не требуют БД. Firebase проверяется через SDK с замоканной сетью;
реальные push-токены и доступ к облаку для прогона не нужны. Зависимость firebase-admin
должна быть установлена, даже если сама отправка отключена.

Для проверки файлов вручную есть [готовые наборы](../../data/synthetic/README.md),
для проверок по HTTP — [Bruno](../bruno/README.md).

Планирование: test_planning_api.py проверяет транзакции, конкуренцию, актуальность и права;
test_planning_boundaries.py — HTTP, матрицы, геометрию и ограничения;
test_planning_datasets.py — шесть наборов в обоих форматах и PostgreSQL.
Эти backend-тесты используют явно названную FeasiblePlanner-фикстуру, а не оптимизатор.
Реальный OR-Tools проверяется в planner/tests и run_planning_e2e.py; фикстура туда не подставляется.

T01: `test_planning_policy.py` проверяет контракт, запрет неизвестных правил и
11 синтетических сравнений целей. Эти сравнения не считаются native-приёмкой A09–A12.
`test_planning_api.py` дополнительно проверяет снимок параметров, смену настроек,
старые планы без параметров, запрет подмены политики, роли и отказ до записи.
`python verify_synthetic.py` проверяет все сохранённые пакеты standard/large,
шесть planning-наборов и Bruno: хеши, количества строк, CSV/XLSX-равенство.
