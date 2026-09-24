# Запуск backend и planner

## Поддерживаемая среда

| Компонент | Поддержка для backend/planner |
| --- | --- |
| Python | CPython 3.12.x; версия записана в `.python-version` |
| Node.js | 24.x LTS для Bruno CLI 4.1.0 в backend API E2E; отдельный frontend job использует 22.x |
| PostgreSQL | 17.x; локальный Compose и CI используют одну основную версию |
| ОС | Ubuntu 24.04 x86-64 — опорная среда CI; Docker Compose запускает Linux-образы backend и planner |
| Docker Compose | Compose CLI 2.17.0 или новее; локальная проверка выполнена на 5.1.1 |
| CI | GitHub Actions, `ubuntu-24.04`, Python 3.12, PostgreSQL 17, Node 24 для Bruno |

Python-зависимости рассчитаны на CPython 3.12. Установка OR-Tools требует готовое
нативное колесо: Docker и CI используют Linux x86-64; пакет 9.15.6755 также публикует
колёса для Linux ARM64, macOS ARM64/x86-64 и Windows x86-64.
Для Node.js сверяйте [таблицу поддержки релизов](https://nodejs.org/en/about/previous-releases):
Node 24 остаётся LTS, Node 20 завершил поддержку 24 марта 2026 года.

## Чистый запуск через Compose

Команды рассчитаны на новый checkout из корня репозитория, установленный Docker Engine
или Docker Desktop с Compose и `curl`. Минимум 2.17.0 нужен для тайм-аута ожидания
здоровья сервисов в `compose up --wait`; [release notes 2.17.0](https://github.com/docker/compose/releases/tag/v2.17.0).
Команды запускают только базу, planner и backend.
Firebase и Geoapify для демонстрации не нужны; планирование через платную матрицу дорог
остаётся выключенным.

```sh
set -eu
umask 077
cp .env.docker.example .env
python3 - <<'PY'
from pathlib import Path
import secrets

env_file = Path(".env")
content = env_file.read_text(encoding="utf-8")
content = content.replace("POSTGRES_PASSWORD=", f"POSTGRES_PASSWORD={secrets.token_hex(32)}", 1)
content = content.replace("JWT_SECRET_KEY=", f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}", 1)
env_file.write_text(content, encoding="utf-8")
PY
chmod 600 .env

docker compose -p beeline-t20 build --no-cache backend planner
docker compose -p beeline-t20 up -d --wait --wait-timeout 600 db planner backend
docker compose -p beeline-t20 exec backend python seed_demo.py
curl -fsS http://127.0.0.1:8000/ready
curl -fsS -o /dev/null -w 'OpenAPI HTTP %{http_code}\n' http://127.0.0.1:8000/openapi.json
docker compose -p beeline-t20 exec backend python -m alembic current
docker compose -p beeline-t20 down -v --remove-orphans
rm .env
```

Первый вызов Compose строит образы без сохранённого слоя зависимостей. В `entrypoint.sh`
миграции выполняются до запуска API; ошибка миграции или выбранного `AUTO_SEED=true`
завершает контейнер с ненулевым кодом. В примере seed запускается отдельно, чтобы не
создавать демо-учётные записи при каждом перезапуске. Последняя команда удаляет только
контейнеры и тома проекта `beeline-t20`.

Проверка готовности возвращает `200` только при доступной БД, текущих миграциях и
отвечающем planner. `/health` показывает liveness процесса. Оба маршрута обходят
Geoapify и Firebase; полный расчёт маршрута требует `PLANNING_ENABLED=true`, внутреннего
`PLANNER_SERVICE_TOKEN` и `GEOAPIFY_API_KEY`.

Для локальной демонстрации можно заполнить БД через `seed_demo.py`. Учётные записи из
этого seed предназначены только для изолированной демонстрационной базы; не открывайте
такой backend в общую сеть и не переносите эти пароли в рабочую среду. В локальном
Compose `FIREBASE_ENABLED=false`, и отсутствие Google credentials не влияет на запуск.
Для реальной отправки push нужно отдельно установить безопасные credentials и включить
Firebase. Секреты остаются в `.env` или secret store; файл `.env` уже добавлен в
`.gitignore`.

## Установка зависимостей для локальных проверок

Из корня репозитория создайте новое окружение и установите backend- и planner-зависимости
с общими ограничениями. OR-Tools ставится из готового бинарного wheel:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir --only-binary=ortools \
  -c constraints.txt -r backend/requirements.txt -r planner/requirements.txt
.venv/bin/python -m pip check
```

Файлы `requirements.txt` задают совместимые диапазоны прямых зависимостей;
`constraints.txt` согласует версии pandas и protobuf для общего окружения.
Firebase Admin и `icalendar` указаны в backend requirements; OR-Tools закреплён
на 9.15.6755 в planner requirements.

## Проверки в CI

Workflow `Backend CI` запускает backend-тесты с PostgreSQL 17, затем синтетические
проверки и Bruno E2E с реальным planner. Отдельная задача `Planner API checks` ставит
`planner/requirements.txt` с общими ограничениями, принудительно выбирает бинарный OR-Tools и выполняет тесты
решателя. Job `Frontend lint and build` находится в том же workflow, но не относится
к этому backend-сценарию.

Результат этого clean-run прогона с версиями среды, миграцией, readiness и отчётами
проверок записан в [T20_CLEAN_RUN.md](T20_CLEAN_RUN.md). В нём нет `.env`, токенов
или заголовков авторизации.
