# Инструкция по запуску в Docker

В репозитории настроена полная оркестрация всех компонентов системы через Docker Compose:
- **`frontend`** (Next.js 16) — порт `3000`
- **`backend`** (FastAPI) — порт `8000` (Swagger UI: `http://localhost:8000/docs`)
- **`planner`** (Микросервис оптимизации маршрутов OR-Tools) — порт `8001` (Swagger UI: `http://localhost:8001/docs`)
- **`db`** (PostgreSQL 16) — порт `5432`

---

## 1. Быстрый запуск

1. **Создайте файл переменных окружения из шаблона:**
   ```bash
   cp .env.docker.example .env
   ```
   *(В Windows PowerShell: `Copy-Item .env.docker.example .env`)*

2. **Запустите сборку и старт всех сервисов:**
   ```bash
   docker compose up --build
   ```
   Или в фоновом режиме:
   ```bash
   docker compose up --build -d
   ```

3. **Проверьте доступность сервисов:**
   - Веб-приложение: [http://localhost:3000](http://localhost:3000)
   - Основной API Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Planner API Swagger: [http://localhost:8001/docs](http://localhost:8001/docs)
   - Healthcheck бэкенда: [http://localhost:8000/health](http://localhost:8000/health)

---

## 2. Миграции и наполнение демо-данными (AUTO_SEED)

- **Миграции Alembic:**
  При старте контейнера `backend` автоматически запускается скрипт `entrypoint.sh`, который накатывает все свежие миграции (`alembic upgrade head`) после успешного прохождения healthcheck базы данных.
- **Флаг `AUTO_SEED`:**
  В файле `.env` вы можете выставить `AUTO_SEED=true`:
  ```dotenv
  AUTO_SEED=true
  ```
  В этом случае при запуске бэкенда автоматически отработает `seed_demo.py`, создавая тестовых пользователей (наблюдателей, инженеров со сменами и навыками), адреса и заявки в Санкт-Петербурге. Скрипт идемпотентен (не создает дубликаты при перезапусках).
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
