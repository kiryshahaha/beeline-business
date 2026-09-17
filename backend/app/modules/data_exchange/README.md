# Импорт и экспорт

Обмен всеми предметными таблицами через авторизованный API диспетчера.
Публичный контракт, поля и примеры: [DATA_EXCHANGE.md](../../../../docs/DATA_EXCHANGE.md).

| Файл | Что делает |
| --- | --- |
| `registry.py` | Явный allowlist 21 таблицы, исключение секретов, порядок зависимостей |
| `formats.py` | UTF-8 CSV, ZIP и XLSX; типизация, лимиты, защита от формул, сериализация |
| `service.py` | Транзакция, перенос ID/связей, проверка ролей/склада/GeoJSON, квитанции |
| `models.py` | Служебная таблица `data_imports`: fingerprint, результат, время |
| `router.py` | `/api/v1/data/schema`, `/export`, `/import`; доступ observer |

Новая предметная таблица не попадёт в выгрузку случайно: её нужно добавить в
allowlist, синтетический генератор и тесты. ID внутри JSON требуют явного переноса
в service; SQLAlchemy не знает об этих неявных внешних ключах.

Нельзя заменять атомарный импорт циклом HTTP-запросов к остальным модулям:
их отдельные транзакции оставят частичный пакет при ошибке. Экспорт использует
один REPEATABLE READ снимок всех таблиц, без лимитов обычных списочных эндпоинтов.

Проверки без БД: `python -m unittest tests.test_data_formats -v`.
Проверки БД/API, из backend:

```powershell
python -m unittest tests.test_exchange_and_routes_api tests.test_exchange_roundtrip_and_migration -v
```
