import { useQuery, useMutation } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Хук для получения списка маршрутов с фильтрацией (ручка GET /api/v1/routes)
 */
export function useRoutes({
  worker_id,
  route_date,
  limit = 100,
  offset = 0,
} = {}) {
  const { token } = useAuth();

  const { data: routes = [], ...routesData } = useQuery({
    queryKey: ["routesList", worker_id, route_date, limit, offset],
    enabled: !!token,

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(worker_id != null && { worker_id: String(worker_id) }),
        ...(route_date && { route_date }),
        limit: String(limit),
        offset: String(offset),
      });

      const res = await apiFetch(`/routes?${urlParams}`);
      if (!res.ok) throw new Error("Ошибка в получении маршрутов");
      return res.json();
    },
    staleTime: 60 * 1000,
  });

  return { routes, routesData };
}

/**
 * Хук для получения точного GeoJSON файла маршрута (ручка GET /api/v1/routes/{id}/geojson)
 */
export function useRouteGeoJson(routeId) {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["routeGeoJson", routeId],
    enabled: !!token && !!routeId,
    queryFn: async () => {
      const res = await apiFetch(`/routes/${routeId}/geojson`);
      if (!res.ok) throw new Error(`Не удалось загрузить GeoJSON для маршрута #${routeId}`);
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Хук для расчета маршрута по дорожной сети через ручку бэкенда (POST /api/v1/routes/calculate)
 */
export function useCalculateRoute() {
  return useMutation({
    mutationFn: async ({ origin, destination, mode = "drive" }) => {
      const res = await apiFetch("/routes/calculate", {
        method: "POST",
        body: JSON.stringify({
          origin: { latitude: origin.latitude, longitude: origin.longitude },
          destination: { latitude: destination.latitude, longitude: destination.longitude },
          mode,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Не удалось рассчитать маршрут через API бэкенда");
      }

      return res.json();
    },
  });
}
