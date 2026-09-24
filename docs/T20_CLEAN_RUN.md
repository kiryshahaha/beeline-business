# T20. Протокол чистого backend запуска

Проверка выполнена 24.09.2026 в отдельной рабочей копии от `main` на ревизии
`c759197`. Результат относится к backend, planner, PostgreSQL и API E2E; frontend job
не запускался.

## Среда

| Компонент | Версия при проверке |
| --- | --- |
| Хост | macOS 26.6.2, arm64 |
| Docker Engine | 29.4.0 |
| Docker Compose | 5.1.1 |
| Backend и planner | CPython 3.12.14, образы `linux/arm64` |
| PostgreSQL | 17.10 |
| Bruno CLI | 4.1.0 |
| Node.js для backend E2E | 24.21.0 |

## Чистый запуск

Compose-конфигурация прошла `docker compose config --quiet`. Backend и planner
собрались без кэша из `python:3.12-slim-bookworm`; затем команда `docker compose up`
дождалась статуса `healthy` у PostgreSQL, planner и backend. Для Compose переменные
секретов задавались временными случайными значениями; сами значения в отчёт не попали.

Backend применил Alembic `0020 (head)`. После `seed_demo.py` в БД находились восемь
демонстрационных заявок. `/ready` вернул:

```json
{"status":"ready","checks":{"database":"ok","migrations":"ok","planner":"ok"}}
```

`GET /openapi.json` ответил HTTP 200. Bruno system smoke проверил `/health` и `/ready`:
2 запроса, 2 теста и 2 assertions прошли.

## Проверки

| Проверка | Результат |
| --- | --- |
| Backend unittest с PostgreSQL 17 | 379/379 |
| Planner unittest с нативным OR-Tools 9.15.6755 | 16/16 |
| Ruff backend и planner | Ошибок нет |
| Ruff format backend и planner | Все файлы отформатированы |
| `pip check` backend, planner и совместного E2E-образа | Нарушений нет |
| Генерация синтетического набора | 1 500 заявок, 120 сотрудников, 7 дней |
| Повторный `seed_synthetic.py` | Первый запуск создал seed; второй вернул `duplicate=true` |
| `verify_synthetic.py` | 18 файлов, 9 CSV/XLSX пар, 11 policy-сравнений |
| Полный backend/planner Bruno E2E на Node 24 | 214/214 запросов, 183/183 теста, 272/272 assertions |

Полный E2E использовал реальные backend и OR-Tools planner, отдельную временную
PostgreSQL-схему и локальную Geoapify fixture. Bruno JUnit завершился с 0 failures,
0 errors и 0 skipped. CLI запуск исключал заголовки и тела запросов/ответов из отчёта;
поиск тестовых логов не нашёл токены, `Authorization` или тестовые секреты.

GitHub Actions на этой ветке не запускался: изменения оставлены незакоммиченными
для проверки владельцем репозитория. Локально пройдены backend job команды workflow;
отдельный frontend job не запускался.
