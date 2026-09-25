import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useOffices() {
  const { token } = useAuth();

  const { data: offices = [], ...officesData } = useQuery({
    queryKey: ["officesList", token],
    queryFn: async () => {
      const res = await apiFetch("/offices", token);
      if (!res.ok) throw new Error("Ошибка в получении офисов");
      return res.json();
    },
    staleTime: 5 * 60 * 1000, // cache for 5 minutes
  });

  return { offices, officesData };
}
