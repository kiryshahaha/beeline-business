# Расчёт VRPTW

schemas.py — единственный строгий контракт /api/v1/solve: отдельные матрицы по
профилям транспорта, смены, service_times, окна и разрешённые исполнители.
service.py — OR-Tools RoutingModel. Начальное решение PARALLEL_CHEAPEST_INSERTION,
улучшение GUIDED_LOCAL_SEARCH. Обслуживание входит во временную размерность;
стоимость — минуты поездок и штрафы пропуска. vehicle_fixed_cost = 0.
router.py проверяет X-Planner-Token и ограничивает параллельные расчёты.

vehicle_id и node — индексы, не ID из БД. Время в минутах от начала дня, расстояние
в метрах. arrival_time — конкретное начало обслуживания после ожидания.
Ответ различает FEASIBLE, OPTIMAL, INFEASIBLE и NOT_SOLVED.

Backend planning готовит вход, проверяет ответ, запрашивает дорожную геометрию и
атомарно сохраняет назначения и маршруты. Полная документация: [planner](../../../README.md).
