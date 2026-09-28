import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useTickets({
  status,
  city_id,
  service_area_id,
  district_id,
  brigade_id,
  limit = 20,
  offset = 0,
} = {}) {
  const { token } = useAuth();
  const effectiveAreaId = service_area_id ?? district_id;

  const { data: tickets = [], ...ticketsData } = useQuery({
    queryKey: ["ticketsList", status, city_id, effectiveAreaId, brigade_id, limit, offset],
    enabled: !!token,

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(status && { status }),
        ...(city_id && { city_id: String(city_id) }),
        ...(effectiveAreaId && { service_area_id: String(effectiveAreaId) }),
        ...(brigade_id && { brigade_id: String(brigade_id) }),
        limit: String(limit),
        offset: String(offset),
      });

      const res = await apiFetch(`/tickets?${urlParams}`);
      if (!res.ok) throw new Error("Ошибка в получении заявок");
      return res.json();
    },
  });

  return { tickets, ticketsData };
}


