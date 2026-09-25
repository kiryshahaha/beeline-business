import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useNotificationsHistory({ limit = 20, offset = 0 } = {}) {
  const { token } = useAuth();

  const { data: notifications = [], ...queryInfo } = useQuery({
    queryKey: ["notificationsHistory", limit, offset],
    enabled: !!token,
    queryFn: async () => {
      const urlParams = new URLSearchParams({ limit, offset });
      const res = await apiFetch(`/notifications?${urlParams}`);
      if (!res.ok) throw new Error("Ошибка в получении уведомлений");
      return res.json();
    },
    // Кэшируем на 5 минут, но WS будет инвалидировать этот кэш при новых событиях
    staleTime: 5 * 60 * 1000,
  });

  return { notifications, ...queryInfo };
}
