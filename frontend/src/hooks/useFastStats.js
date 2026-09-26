import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useFastStats({ office_id } = {}) {
  const { token } = useAuth();

  const { data: stats = null, ...queryData } = useQuery({
    queryKey: ["fastStats", office_id],
    
    queryFn: async () => {
      const urlParams = new URLSearchParams();
      if (office_id) urlParams.append("office_id", office_id);

      const qs = urlParams.toString();
      const url = qs ? `/analytics/fast-stats?${qs}` : `/analytics/fast-stats`;
      
      const res = await apiFetch(url);
      
      if (!res.ok) {
        throw new Error("Ошибка при получении быстрых статистик");
      }
      
      return res.json();
    },
    
    enabled: !!token,
    refetchInterval: 30000, // Update every 30 seconds
  });

  return { stats, ...queryData };
}
