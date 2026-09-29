import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useWorkTypes() {
  const { token } = useAuth();

  const { data: workTypes = [], ...workTypesData } = useQuery({
    queryKey: ["workTypesList"],
    enabled: !!token,
    queryFn: async () => {
      const res = await apiFetch("/work-types");
      if (!res.ok) throw new Error("Ошибка в получении видов работ");
      return res.json();
    },
  });

  return { workTypes, workTypesData };
}
