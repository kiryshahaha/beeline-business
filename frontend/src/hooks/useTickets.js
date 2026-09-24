import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useTickets({
  status,
  city_id,
  district_id,
  limit = 20,
  offset = 0,
} = {}) {
  const { token } = useAuth();

  const { data: tickets = [], ...ticketsData } = useQuery({
    queryKey: ["ticketsList", token, status, city_id, district_id, limit, offset],

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(status && { status }),
        ...(city_id && { city_id }),
        ...(district_id && { district_id }),
        limit: String(limit),
        offset: String(offset),
      });

      const res = await apiFetch(`/tickets?${urlParams}`, token);
      if (!res.ok) throw new Error("Ошибка в получении заявок");
      return res.json();
    },
  });

  return { tickets, ticketsData };
}
