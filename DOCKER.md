# Инструкция по запуску в Docker

В репозитории настроена полная оркестрация всех компонентов системы через Docker Compose:
- **`nginx`** (Reverse Proxy / Единая точка входа) — порт `80` (настраивается через `NGINX_PORT`)
- **`frontend`** (Next.js 16) — порт `3000` (внутри сети `app-network`, также проброшен для локальной отладки)
- **`backend`** (FastAPI) — порт `8000` (внутри сети `app-network`, также проброшен для локальной отладки)
- **`planner`** (Микросервис оптимизации маршрутов OR-Tools) — порт `8001`
- **`db`** (PostgreSQL 17) — порт `5432`
- **`assistant`** / **`ollama`** (Чат-помощник и локальная LLM) — порты `8002` / `11434`

---

## 1. Быстрый запуск

1. **Создайте файл переменных окружения из шаблона:**
   ```bash
   cp .env.docker.example .env
   ```
   *(В Windows PowerShell: `Copy-Item .env.docker.example .env`)*

   Шаблон оставляет `POSTGRES_PASSWORD` и `JWT_SECRET_KEY` пустыми. Заполните их
   случайными значениями; безопасный скрипт для этого находится в
   [руководстве runtime](Артефакты_нейронки/RUNTIME.md). Compose остановится с понятной ошибкой,
   пока обязательные секреты не заданы.

   Для планирования задайте в `.env` `PLANNING_ENABLED=true`, непустой
   `PLANNER_SERVICE_TOKEN` и действующий `GEOAPIFY_API_KEY`. Compose передаст один
   внутренний token backend и planner. Внутри сети Docker адрес решателя —
   `http://planner:8001`; `localhost` в контейнере backend указывает на сам backend.
   Срок действия preview и лимиты времени задаются `PLANNING_PREVIEW_TTL_SECONDS`,
   `PLANNING_SOLVE_TIME_LIMIT_SECONDS`, `PLANNING_TOTAL_TIMEOUT_SECONDS`.

2. **Запустите сборку и старт всех сервисов:**
   ```bash
   docker compose up --build
   ```
   Или в фоновом режиме:
   ```bash
   docker compose up --build -d
   ```

3. **Проверьте доступность сервисов:**
   **Единая точка входа (Nginx, порт 80):**
   - Веб-приложение (фронтенд): [http://localhost](http://localhost)
   - Основной API Swagger: [http://localhost/docs](http://localhost/docs)
   - Схема OpenAPI: [http://localhost/openapi.json](http://localhost/openapi.json)
   - Liveness API: [http://localhost/health](http://localhost/health)
   - Готовность БД, миграций и planner: [http://localhost/ready](http://localhost/ready)
   - Healthcheck Nginx: [http://localhost/nginx-health](http://localhost/nginx-health)
   - WebSocket уведомления: `ws://localhost/api/v1/notifications/ws`

   **Прямой доступ к сервисам (для локальной разработки/отладки):**
   - Frontend напрямую: [http://localhost:3000](http://localhost:3000)
   - Backend API напрямую: [http://localhost:8000](http://localhost:8000) (Swagger: `http://localhost:8000/docs`)
   - Planner API Swagger: [http://localhost:8001/docs](http://localhost:8001/docs)

   `/ready` проверяет зависимости backend, не обращаясь к Geoapify. Для расчёта нужны также
   координаты офисов и заявок, будущие смены, транспорт, навыки, резерв оборудования
   и явно настроенные правила видов работ через
   `PUT /api/v1/work-types/{id}/planning-rules`. Расчёт запускается через
   `POST /api/v1/planning/preview`, подтверждение — через
   `POST /api/v1/planning/plans/{plan_id}/apply` от имени observer.
   Подробнее: [контракт и ограничения планирования](backend/app/modules/planning/README.md).

---

## 2. Миграции и наполнение демо-данными (AUTO_SEED)

- **Миграции Alembic:**
  При старте контейнера `backend` автоматически запускается скрипт `entrypoint.sh`, который накатывает все свежие миграции (`alembic upgrade head`) после успешного прохождения healthcheck базы данных.
- **Флаг `AUTO_SEED`:**
  В файле `.env` вы можете выставить `AUTO_SEED=true`:
  ```dotenv
  AUTO_SEED=true
  ```
  В этом случае при запуске бэкенда автоматически отработает `seed_demo.py`, создавая тестовых пользователей (наблюдателей, инженеров со сменами и навыками), адреса и заявки демонстрационного дня в Москве (три участка кейса, реальные дома OpenStreetMap). Скрипт идемпотентен (не создает дубликаты при перезапусках).
- **Ручной сидинг:**
  Вы можете вызвать наполнение данными вручную в любой момент:
  ```bash
  docker compose exec backend python seed_demo.py
  ```

---

## 3. Полезные команды

- **Просмотр логов всех сервисов:**
  ```bash
  docker compose logs -f
  ```
- **Просмотр логов конкретного сервиса:**
  ```bash
  docker compose logs -f backend
  ```
- **Остановка контейнеров:**
  ```bash
  docker compose down
  ```
- **Остановка с удалением тома базы данных (полный сброс данных):**
  ```bash
  docker compose down -v
  ```
- **Пересборка конкретного сервиса после правок:**
  ```bash
  docker compose up -d --build frontend
  ```
