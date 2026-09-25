# Приложение backend

`main.py` создаёт FastAPI, подключает CORS и роутеры, запускает/останавливает фоновый
диспетчер уведомлений и дополняет OpenAPI примерами. `/health` проверяет liveness;
`/ready` проверяет PostgreSQL, текущую ревизию Alembic и доступность planner.

- [core](core/README.md): настройки и криптографические операции.
- [db](db/README.md): metadata, реестр таблиц, engine и жизненный цикл сессий.
- [modules](modules/README.md): предметный код, API и модели.

Команды чистого запуска backend и planner находятся в [руководстве runtime](../../docs/RUNTIME.md).
Импорт модулей сам по себе не должен выполнять миграции, seeding или запросы к БД.
