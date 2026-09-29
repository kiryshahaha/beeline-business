import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useTickets({
  status,
  city_id,
  service_area_id,
  district_id,
  brigade_id,
  date,
  date_from,
  date_to,
  limit = 20,
  offset = 0,
  fetchAll = false,
} = {}) {
  const { token } = useAuth();
  const effectiveAreaId = service_area_id ?? district_id;

  const { data: tickets = [], ...ticketsData } = useQuery({
    queryKey: ["ticketsList", status, city_id, effectiveAreaId, brigade_id, date, date_from, date_to, limit, offset, fetchAll],
    enabled: !!token,

    queryFn: async () => {
      const baseParams = {
        ...(status && { status }),
        ...(city_id && { city_id: String(city_id) }),
        ...(effectiveAreaId && { service_area_id: String(effectiveAreaId) }),
        ...(brigade_id && { brigade_id: String(brigade_id) }),
        ...(date && { date: String(date) }),
        ...(date_from && { date_from: String(date_from) }),
        ...(date_to && { date_to: String(date_to) }),
      };

      if (!fetchAll) {
        const urlParams = new URLSearchParams({
          ...baseParams,
          limit: String(limit),
          offset: String(offset),
        });
        const res = await apiFetch(`/tickets?${urlParams}`);
        if (!res.ok) throw new Error("Ошибка в получении заявок");
        return res.json();
      }

      // Выгрузка всех страниц до конца пачками по 100 штук (в соответствии со спецификацией API)
      const allItems = [];
      let currentOffset = 0;
      const batchSize = 100;
      const maxPages = 50;

      for (let page = 0; page < maxPages; page++) {
        const urlParams = new URLSearchParams({
          ...baseParams,
          limit: String(batchSize),
          offset: String(currentOffset),
        });
        const res = await apiFetch(`/tickets?${urlParams}`);
        if (!res.ok) throw new Error("Ошибка в получении заявок");
        const batch = await res.json();
        if (!Array.isArray(batch) || batch.length === 0) break;
        allItems.push(...batch);
        if (batch.length < batchSize) break;
        currentOffset += batchSize;
      }
      return allItems;
    },
  });

  return { tickets, ticketsData };
}


