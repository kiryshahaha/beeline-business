# Автоматические проверки

`backend-tests.yml` запускается на push, pull_request и вручную. Три независимых job:

1. Backend: PostgreSQL 17, Python 3.12, проверка зависимостей, Ruff, unittest,
   генерация синтетики, повторный seed, миграции и вся коллекция Bruno 4.1.0.
2. Frontend: Node.js 22, npm ci, ESLint и production build Next.js.
3. Planner: Python 3.12, зависимости и unittest с реальными assertions API солвера.

Тестовые подключения задаются только к временному контейнеру. Интеграционные тесты
используют отдельные схемы, а synthetic seed — synthetic_42. Bruno использует
public с отдельными демонстрационными данными. Поэтому большие синтетические наборы
не меняют старые ожидания пагинации Bruno.

У workflow только contents:read. Checkout не сохраняет Git credentials.
Повторные запуски одной ветки отменяют предыдущий. Отчёт Bruno и лог API сохраняются
как artifact даже при ошибке. Workflow не публикует и не развёртывает приложение.
