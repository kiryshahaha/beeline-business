import { useQueries } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useLocations(ids = []) {
  const { token } = useAuth();

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["location", id],

      queryFn: async () => {
        const res = await apiFetch(`/location/${id}`, token);

        if (!res.ok) {
          throw new Error(`Ошибка получения локации ${id}`);
        }

        return res.json();
      },

      enabled: !!id,
    })),
  });

  return queries;
}
