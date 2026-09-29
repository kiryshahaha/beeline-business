import { useQuery, useMutation } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Хук для получения списка маршрутов с фильтрацией (ручка GET /api/v1/routes)
 */
export function useRoutes({
  worker_id,
  route_date,
  date_from,
  date_to,
  limit = 100,
  offset = 0,
} = {}) {
  const { token } = useAuth();

  const { data: routes = [], ...routesData } = useQuery({
    queryKey: ["routesList", worker_id, route_date, date_from, date_to, limit, offset],
    enabled: !!token,

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        ...(worker_id != null && { worker_id: String(worker_id) }),
        ...(route_date && { route_date }),
        ...(date_from && { route_date_from: date_from }),
        ...(date_to && { route_date_to: date_to }),
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
      // 1. Try backend calculate endpoint first
      try {
        const res = await apiFetch("/routes/calculate", {
          method: "POST",
          body: JSON.stringify({
            origin: { latitude: origin.latitude, longitude: origin.longitude },
            destination: { latitude: destination.latitude, longitude: destination.longitude },
            mode,
          }),
        });

        if (res.ok) {
          return await res.json();
        }
      } catch {
        // Continue to fallback
      }

      // 2. Try POST /routes (alternate backend endpoint)
      try {
        const res2 = await apiFetch("/routes", {
          method: "POST",
          body: JSON.stringify({
            origin: { latitude: origin.latitude, longitude: origin.longitude },
            destination: { latitude: destination.latitude, longitude: destination.longitude },
            mode,
          }),
        });

        if (res2.ok) {
          return await res2.json();
        }
      } catch {
        // Continue to fallback
      }

      // 3. Fallback to public OSRM router
      try {
        const osrmUrl = `https://router.project-osrm.org/route/v1/driving/${origin.longitude},${origin.latitude};${destination.longitude},${destination.latitude}?overview=full&geometries=geojson`;
        const osrmRes = await fetch(osrmUrl);
        if (osrmRes.ok) {
          const osrmData = await osrmRes.json();
          if (osrmData.code === "Ok" && osrmData.routes?.[0]) {
            const r = osrmData.routes[0];
            return {
              distance_meters: r.distance,
              duration_seconds: r.duration,
              geometry: r.geometry,
            };
          }
        }
      } catch {
        // Continue to fallback
      }

      // 4. Straight-line fallback
      const distKm = Math.hypot(
        (destination.latitude - origin.latitude) * 111,
        (destination.longitude - origin.longitude) * 65
      );
      return {
        distance_meters: distKm * 1000,
        duration_seconds: (distKm / 35) * 3600,
        geometry: {
          type: "LineString",
          coordinates: [
            [origin.longitude, origin.latitude],
            [destination.longitude, destination.latitude],
          ],
        },
      };
    },
  });
}
