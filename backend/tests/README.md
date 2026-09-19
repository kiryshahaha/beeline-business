# Проверки backend

Из backend: `python -m unittest discover -s tests -v`.
Нужны установленные requirements и TEST_DATABASE_URL на отдельную PostgreSQL БД
с именем `*_test`. Без переменной интеграционные классы пропускаются.

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
| `test_notifications*`, `test_firebase_gateway.py` | Очередь, WebSocket, токены и граница SDK Firebase |
| `test_calendar_feed_api.py` | Файл iCalendar, хранение хеша токена, перевыпуск, отзыв и роли |
| `test_database.py`, `test_locations_api.py`, `test_*migration.py` | Ограничения БД и миграции |
| `test_seed_demo.py`, `test_openapi.py`, `test_enum_types.py`, `test_health.py` | Демонстрационные данные и публичные контракты |

Файловые тесты не требуют БД. Firebase проверяется через SDK с замоканной сетью;
реальные push-токены и доступ к облаку для прогона не нужны. Зависимость firebase-admin
должна быть установлена, даже если сама отправка отключена.

Для проверки файлов вручную есть [готовые наборы](../../data/synthetic/README.md),
для проверок по HTTP — [Bruno](../bruno/README.md).
