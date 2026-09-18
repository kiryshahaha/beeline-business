# Приложение backend

`main.py` создаёт FastAPI, подключает CORS и роутеры, запускает/останавливает фоновый
диспетчер уведомлений и дополняет OpenAPI примерами. `/health` — liveness без SQL.

- [core](core/README.md): настройки и криптографические операции.
- [db](db/README.md): metadata, реестр таблиц, engine и жизненный цикл сессий.
- [modules](modules/README.md): предметный код, API и модели.

Из backend: `python -m uvicorn app.main:app --port 8000` после применения миграций.
Импорт модулей сам по себе не должен выполнять миграции, seeding или запросы к БД.
