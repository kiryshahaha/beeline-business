# Автоматические проверки

backend-tests.yml запускается на push, pull_request и workflow_dispatch.

- Backend: Python 3.12, PostgreSQL 17, полные зависимости backend и planner,
  Ruff, все unittest, генерация синтетики и повторный seed.
- HTTP E2E в том же job: run_planning_e2e.py создаёт уникальную схему, запускает
  backend, настоящий OR-Tools planner и контролируемый Geoapify, затем всю Bruno 4.1.0.
- Planner: все unittest, Ruff и сверка контракта с backend. Нативный OR-Tools обязателен.
- Frontend: Node.js 22, npm ci, ESLint и production build.

Отсутствие TEST_DATABASE_URL приводит к ошибке. Платные Geoapify-вызовы не нужны:
тестовый провайдер возвращает искусственные предсказуемые дороги и матрицы.
В обязательном E2E сам решатель не подменяется.

Синтетический seed использует synthetic_42; E2E — новую временную схему.
Процессы завершаются и схема удаляется в finally, в том числе при ошибке.
Логи и JUnit сохраняются как artifact из backend/.local/planning-e2e.

У workflow только contents:read; checkout не сохраняет Git credentials.
Workflow не развёртывает приложение и не публикует код.
