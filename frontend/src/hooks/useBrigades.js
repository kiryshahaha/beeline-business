import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useBrigades() {
  const { token } = useAuth();

  const { data: brigades = [], ...brigadesData } = useQuery({
    queryKey: ["brigadesList", token],
    queryFn: async () => {
      const res = await apiFetch("/brigades", token);
      if (!res.ok) throw new Error("Ошибка в получении бригад");
      return res.json();
    },
  });

  return { brigades, brigadesData };
}
