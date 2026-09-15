import { useQuery } from "@tanstack/react-query";

export function useTickets({
  status,
  city_id,
  district_id,
  limit = 20,
  offset = 0,
} = {}) {
  const { data: tickets, ...ticketsData } = useQuery({
    queryKey: ["ticketsList", status, city_id, district_id, limit, offset],

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(status && { status }),
        ...(city_id && { city_id }),
        ...(district_id && { district_id }),
        limit: String(limit),
        offset: String(offset),
      });

      const rawRes = await fetch(
        `${process.env.NEXT_PUBLIC_ENDPOINT}/tickets?${urlParams}`,
      );

      if (!rawRes.ok) {
        throw new Error("Ошибка в получении записей");
      }

      return rawRes.json();
    },
  });

  return { tickets, ticketsData };
}
