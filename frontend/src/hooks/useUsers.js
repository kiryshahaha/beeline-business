import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useUsers({ role, brigade_id } = {}) {
  const { token } = useAuth();

  const { data: users = [], ...usersData } = useQuery({
    queryKey: ["usersList", role, brigade_id],
    enabled: !!token,
    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(role && { role }),
        ...(brigade_id && { brigade_id }),
      });

      const res = await apiFetch(`/users?${urlParams}`);
      if (!res.ok) throw new Error("Ошибка в получении пользователей");
      return res.json();
    },
  });

  return { users, usersData };
}


