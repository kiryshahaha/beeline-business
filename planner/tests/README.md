# Проверки planner

`test_api_contract.py` содержит unittest assertions: health, выполнимый маршрут,
упорядоченное время с учётом переезда/работы, расстояние, недопустимый исполнитель
и неверные размеры матрицы. Запуск из planner:

```powershell
python -m unittest discover -s tests -p test_api_contract.py -v
```

`test_solve.py` и `test_manual.py` — ранее существовавшие демонстрационные скрипты:
они печатают ответы через TestClient, но не содержат проверок результата.
`generate_strong.py` готовит входные данные для экспериментов с солвером.
CI запускает новый файл с assertions явно, чтобы вывод демо не выдавался за тесты.
Нужны зависимости из ../requirements.txt, включая OR-Tools и HTTPX.
