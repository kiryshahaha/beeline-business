// frontend/src/hooks/worker/useWorkerRoutes.js
import { useQuery } from "@tanstack/react-query";
import { fetchWorkerRoutes } from "@/lib/worker/api";
import { getTodayMsk } from "@/lib/worker/time";

export function useWorkerRoutes(workerId, date) {
  const targetDate = date || getTodayMsk();

  const query = useQuery({
    queryKey: ["workerRoutes", workerId, targetDate],
    queryFn: () => fetchWorkerRoutes(workerId, targetDate),
    enabled: Boolean(workerId),
    staleTime: 30000,
  });

  const routes = query.data || [];

  // Pick route with is_current_plan === true, or fallback to highest day_revision
  let currentRoute = null;
  if (Array.isArray(routes) && routes.length > 0) {
    currentRoute = routes.find((r) => r.is_current_plan === true);
    if (!currentRoute) {
      const sorted = [...routes].sort(
        (a, b) => (b.day_revision ?? 0) - (a.day_revision ?? 0)
      );
      currentRoute = sorted[0];
    }
  }

  return {
    ...query,
    routes,
    currentRoute,
  };
}
