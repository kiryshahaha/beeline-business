import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Хук для получения расписания дня (бригады → воркеры → таймлайн задач).
 * Ручка GET /api/v1/schedule?date=YYYY-MM-DD&office_id=N
 */
export function useSchedule({ date, office_id } = {}) {
  const { token } = useAuth();

  const queryInfo = useQuery({
    queryKey: ["schedule", date, office_id],
    enabled: !!token,
    refetchInterval: 30000,

    queryFn: async () => {
      const urlParams = new URLSearchParams();
      if (date) urlParams.append("date", date);
      if (office_id) urlParams.append("office_id", String(office_id));

      const qs = urlParams.toString();
      const url = qs ? `/schedule?${qs}` : "/schedule";
      const res = await apiFetch(url);

      if (!res.ok) {
        throw new Error("Ошибка при получении расписания");
      }

      return res.json();
    },
  });

  return {
    schedule: queryInfo.data || null,
    ...queryInfo,
  };
}
