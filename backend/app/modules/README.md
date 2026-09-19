# Предметные модули

Модуль объединяет одну область: ORM-модели, HTTP-схемы, SQL, бизнес-правила и роутер.
`models.py` описывает хранение и ограничения БД; `schemas.py` — вход/выход API;
`repository.py` — доступ к данным; `service.py` — бизнес-операции;
`router.py` — HTTP и зависимости доступа. Не каждый модуль содержит все слои.

| Область | Модули |
| --- | --- |
| Адреса | [cities](cities/README.md), [districts](districts/README.md), [streets](streets/README.md), [buildings](buildings/README.md), [entrances](entrances/README.md), [locations](locations/README.md) |
| Люди и организация | [users](users/README.md), [auth](auth/README.md), [offices](offices/README.md), [brigades](brigades/README.md) |
| Работы | [tickets](tickets/README.md), [work_types](work_types/README.md), [comments](comments/README.md), [appliances](appliances/README.md), [notifications](notifications/README.md) |
| Дополнения | [routing](routing/README.md), [data_exchange](data_exchange/README.md) |

Общий реестр ORM находится в `../db/models.py`: Alembic должен увидеть каждую модель.
Новый роутер регистрируется в `../main.py`. Изменение модели требует отдельной миграции.
Границы транзакций контролируются сервисами/роутерами; модуль обмена добавляет пакет
целиком одной транзакцией, не вызывает цепочку отдельных HTTP-операций.
