# Изолированное HTTP-тестирование

Production app.main не импортирует эту папку. backend_app.py требует APP_ENV=test
и БД с окончанием _test. Он заменяет только часы и Geoapify; planner вызывается
настоящим HTTP-клиентом. geoapify_app.py возвращает предсказуемые искусственные
60-секундные переходы для проверки протокола. Это не географическая модель города.

Из backend: `python run_planning_e2e.py --planner-python ../planner/.venv/Scripts/python.exe`.
Для Linux путь к Python: ../planner/.venv/bin/python. Указать TEST_DATABASE_URL.
Сценарий создаёт уникальную схему, применяет миграции, seed_demo, запускает три процесса,
проверяет всю коллекцию Bruno и удаляет только собственную схему. Сохраняет логи и JUnit
в .local/planning-e2e. При ошибке БД/решателя/запроса завершается неуспешно.

Нужны установленные зависимости backend и planner, Node.js и Bruno CLI 4.1.0.
Параметр --bruno-command позволяет использовать заранее установленный CLI.
Ключи внешних сервисов не нужны; платные вызовы Geoapify в этом сценарии отсутствуют.
