# Уведомления

`notification_events` — долговечная очередь/история событий с получателем, заявкой, JSON-данными, попытками и метками доставки. `push_subscriptions` — устройства/токены. Диспетчер обслуживает WebSocket и опциональный Firebase. В тестах реальная внешняя рассылка не нужна; Firebase выключен по умолчанию.

| Файл | Ответственность |
| --- | --- |
| `models.py` | Очередь событий и push-подписки |
| `enums.py` | Виды ticket_assigned и ticket_status_changed |
| `schemas.py` | HTTP-контракты истории и регистрации токенов |
| `repository.py` | Выборка/обновление очереди и токенов |
| `service.py` | История пользователя, регистрация и удаление подписок |
| `dispatcher.py` | Фоновая доставка, повторы и обработка ошибок |
| `connections.py` | Активные WebSocket-соединения процесса |
| `firebase.py` | Граница SDK Firebase и отключённый шлюз |
| `router.py` | HTTP-история, push-токены и WebSocket |

Общий API описан в [backend README](../../../README.md); ограничения существующей
системы — в [аудите](../../../../docs/AUDIT_2026-09-18.md). Миграции находятся
в [migrations](../../../migrations/README.md), проверки — в [tests](../../../tests/README.md).
