import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Получить строку сегодняшней даты по Московскому времени (YYYY-MM-DD).
 */
export function getMskToday() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
}

/**
 * Хук для получения списка дат с задачами и автоматического определения ближайшего доступного дня.
 */
export function useAvailableDates(targetDate) {
  const { token } = useAuth();
  const todayMsk = getMskToday();
  const effectiveTarget = targetDate || todayMsk;

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["availableTicketDates", effectiveTarget],
    enabled: !!token,
    staleTime: 30000,
    queryFn: async () => {
      const res = await apiFetch(`/tickets/dates?target_date=${effectiveTarget}`);
      if (!res.ok) throw new Error("Не удалось получить доступные даты заявок");
      return res.json();
    },
  });

  const dates = data?.dates || [];
  const dateCounts = data?.date_counts || {};
  const hasToday = Boolean(data?.has_today);
  const closestDate = data?.closest_date || todayMsk;
  const totalDates = data?.total_dates || 0;

  return {
    dates,
    dateCounts,
    hasToday,
    closestDate,
    totalDates,
    todayMsk,
    isLoading,
    isError,
    refetch,
  };
}
