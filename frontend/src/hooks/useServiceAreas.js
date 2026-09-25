import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useServiceAreas() {
  const { token } = useAuth();

  const { data: serviceAreas = [], ...serviceAreasData } = useQuery({
    queryKey: ["serviceAreasList"],
    enabled: !!token,
    queryFn: async () => {
      const res = await apiFetch("/service-areas");
      if (!res.ok) throw new Error("Ошибка в получении зон обслуживания");
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  return { serviceAreas, serviceAreasData };
}
