import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

export function useTicketsSummary({ period = "today", office_id } = {}) {
  const { token } = useAuth();

  const { data: summary = null, ...summaryData } = useQuery({
    queryKey: ["ticketsSummary", period, office_id],
    
    queryFn: async () => {
      const urlParams = new URLSearchParams({
        period,
        ...(office_id && { office_id }),
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


