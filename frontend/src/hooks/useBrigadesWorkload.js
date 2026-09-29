import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";


function formatTime(timestamp) {
  if (!timestamp) return "";
  const d = new Date(timestamp);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export function useBrigadesWorkload({ date, date_from, date_to } = {}) {
  const { token } = useAuth();

  const queryInfo = useQuery({
    queryKey: ["brigadesWorkload", date, date_from, date_to],
    enabled: !!token,
    refetchInterval: 30000, // Автообновление каждые 30 секунд

    queryFn: async () => {
      const urlParams = new URLSearchParams();
      if (date) urlParams.append("date", date);
      if (date_from) urlParams.append("date_from", date_from);
      if (date_to) urlParams.append("date_to", date_to);

      const qs = urlParams.toString();
      const url = qs ? `/analytics/brigades-workload?${qs}` : "/analytics/brigades-workload";
      const res = await apiFetch(url);

      if (!res.ok) {
        throw new Error("Ошибка при получении загрузки бригад");
      }

      return res.json();
    },
  });

  const rawList = queryInfo.data || [];

  // Парсинг и обогащение данных для UI
  const brigades = rawList.map((item) => {
    const activeTasks = item.tickets ?? item.active_tickets ?? 0;
    
    // Расчет процента загрузки на основе реального фонда рабочего времени смены
    const busyMinutes = (item.service_minutes || 0) + (item.travel_minutes || 0);
    const shiftMinutes = item.shift_minutes || 0;
    const percent = shiftMinutes > 0
      ? Math.min(100, Math.round((busyMinutes / shiftMinutes) * 100))
      : (activeTasks > 0 ? Math.min(100, activeTasks * 10) : 0);

    // Определение статуса загрузки строго по шкале:
    // 0–50%: Свободна (зеленый #34C759)
    // 51–80%: Оптимально (синий #007AFF)
    // >80%: Перегружена (красный #FF3B30)
    let status = "free";
    let statusLabel = "Свободна";
    let color = "#34C759"; // зеленый 0-50%

    if (percent > 80) {
      status = "overloaded";
      statusLabel = "Перегружена";
      color = "#FF3B30"; // красный >80%
    } else if (percent > 50) {
      status = "optimal";
      statusLabel = "Оптимально";
      color = "#007AFF"; // синий 51-80%
    }

    return {
      id: item.brigade_id,
      name: item.brigade_name,
      activeTasks,
      percent,
      status,
      statusLabel,
      color,
      workers: item.workers,
      availableWorkers: item.available_workers,
      shiftMinutes: item.shift_minutes,
      serviceMinutes: item.service_minutes,
      travelMinutes: item.travel_minutes,
      freeMinutes: item.free_minutes,
      conflicts: item.conflicts,
      completedToday: item.completed_today,
    };
  });

  // Суммарное количество задач в работе по всем бригадам
  const totalActiveTasks = brigades.reduce((sum, b) => sum + b.activeTasks, 0);

  // Время последнего обновления
  const formattedUpdatedAt = queryInfo.dataUpdatedAt
    ? formatTime(queryInfo.dataUpdatedAt)
    : "";

  return {
    brigades,
    totalActiveTasks,
    formattedUpdatedAt,
    ...queryInfo,
  };
}
