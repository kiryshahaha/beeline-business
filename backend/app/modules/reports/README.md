# Отчёты

Модуль формирует файлы по данным заявок и не меняет состояние БД.

## Выгрузка заявок

`GET /api/v1/reports/tickets/export` доступен роли `observer` и принимает фильтры
`status`, `city_id`, `district_id`, `brigade_id`. Параметр `format` выбирает `csv`
или `xlsx`; значение по умолчанию — `xlsx`. Ручка возвращает все совпавшие строки
без пагинации с заголовком `Content-Disposition: attachment`.

`repository.py` получает заявки одним параметризованным SQL-запросом, `service.py`
сериализует общий набор колонок в CSV или XLSX, `router.py` проверяет роль и query-параметры.
