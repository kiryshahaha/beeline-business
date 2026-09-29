import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useTicketsSummary({ period = "today", office_id, date } = {}) {
  const { token } = useAuth();

  const { data: summary = null, ...summaryData } = useQuery({
    queryKey: ["ticketsSummary", period, office_id, date],
    
    queryFn: async () => {
      const urlParams = new URLSearchParams({
        period,
        ...(office_id && { office_id }),
        ...(date && { date }),
      });

      const res = await apiFetch(`/analytics/tickets-summary?${urlParams}`);
      
      if (!res.ok) {
        throw new Error("Ошибка при получении сводки по заявкам");
      }
      
      return res.json();
    },
    
    // Не делать запрос, если токена ещё нет (предотвращает ошибки при монтировании)
    enabled: !!token,
  });

  return { summary, summaryData };
}


