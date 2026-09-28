import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

const MAX_SCALE_CAPACITY = 12; // Базовая шкала емкости задач для визуализации (12 задач = 100%)

function formatTime(timestamp) {
  if (!timestamp) return "";
  const d = new Date(timestamp);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

export function useBrigadesWorkload({ date } = {}) {
  const { token } = useAuth();

  const queryInfo = useQuery({
    queryKey: ["brigadesWorkload", date],
    enabled: !!token,
    refetchInterval: 30000, // Автообновление каждые 30 секунд

    queryFn: async () => {
      const urlParams = new URLSearchParams();
      if (date) urlParams.append("date", date);

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
    
    // Расчет процента загрузки относительно шкалы задач (12 задач = 100%, 8 задач = норма 67%)
    const percent = Math.min(100, Math.round((activeTasks / MAX_SCALE_CAPACITY) * 100));

    // Определение статуса загрузки
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
