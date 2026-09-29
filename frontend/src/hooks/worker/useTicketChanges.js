// frontend/src/hooks/worker/useTicketChanges.js
import { useQuery } from "@tanstack/react-query";
import { fetchTicketChanges } from "@/lib/worker/api";

export function useTicketChanges(ticketId, options = {}) {
  return useQuery({
    queryKey: ["ticketChanges", ticketId],
    queryFn: () => fetchTicketChanges(ticketId),
    enabled: Boolean(ticketId),
    staleTime: 10000,
    ...options,
  });
}
