import { apiFetch } from "@/lib/apiFetch";
import { useAuth } from "@/providers/AuthProvider";
import { useQuery } from "@tanstack/react-query";

export function useLocation({ id }) {
  const { token } = useAuth();
  const { data: location, ...locationData } = useQuery({
    queryKey: ["location", id],
    queryFn: async () => {
      const res = await apiFetch(`/location/${id}`);
      if (!res.ok) {
        throw new Error("Ошибка получения локации");
      }
      return res.json();
    },
    enabled: !!id,
  });
  return { location, locationData };
}
