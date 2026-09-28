"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Хук для расчета дорожного реалистичного маршрута между всеми задачами выбранного инженера
 */
export function useWorkerTasksRoute(selectedWorker, workerTickets = [], locationById = null, offices = []) {
  const { token } = useAuth();

  // 1. Сортируем задачи воркера в порядке визита
  const sortedTasks = (workerTickets || [])
    .filter((t) => t.location?.latitude != null && t.location?.longitude != null)
    .sort((a, b) => {
      const timeA = new Date(a.planned_start_at || a.visit_window_start || a.id).getTime();
      const timeB = new Date(b.planned_start_at || b.visit_window_start || b.id).getTime();
      return timeA - timeB;
    });

  // 2. Ищем базу инженера
  let startLocation = null;
  if (selectedWorker?.location?.latitude != null && selectedWorker?.location?.longitude != null) {
    startLocation = {
      latitude: Number(selectedWorker.location.latitude),
      longitude: Number(selectedWorker.location.longitude),
      label: `База: ${[selectedWorker.name, selectedWorker.surname].filter(Boolean).join(" ")}`,
    };
  } else if (selectedWorker?.worker_profile?.start_location_id && locationById) {
    const loc = locationById.get(selectedWorker.worker_profile.start_location_id);
    if (loc?.latitude != null && loc?.longitude != null) {
      startLocation = {
        latitude: Number(loc.latitude),
        longitude: Number(loc.longitude),
        label: `База: ${[selectedWorker.name, selectedWorker.surname].filter(Boolean).join(" ")}`,
      };
    }
  }

  // Если нет базы инженера, но есть офис обслуживания
  if (!startLocation && offices && offices.length > 0) {
    const off = offices[0];
    if (off.latitude != null && off.longitude != null) {
      startLocation = {
        latitude: Number(off.latitude),
        longitude: Number(off.longitude),
        label: off.office_name || "Офис обслуживания",
      };
    }
  }

  // 3. Формируем список опорных точек
  const points = [];
  if (startLocation) {
    points.push({
      ...startLocation,
      isStart: true,
      sequence: 0,
      address: startLocation.label,
    });
  }

  sortedTasks.forEach((t, idx) => {
    points.push({
      latitude: Number(t.location.latitude),
      longitude: Number(t.location.longitude),
      label: `Заявка #${t.id}: ${t.title || ""}`,
      ticket_id: t.id,
      ticket: t,
      sequence: idx + 1,
      isStart: false,
      address: t.location?.address || t.address || "",
    });
  });

  const canRoute = Boolean(token && selectedWorker && points.length >= 2);

  const queryKey = [
    "workerTasksRoute",
    selectedWorker?.id,
    points.map((p) => `${p.latitude},${p.longitude}`).join(";"),
  ];

  const query = useQuery({
    queryKey,
    enabled: canRoute,
    queryFn: async () => {
      const origin = points[0];
      const destination = points[points.length - 1];
      const waypoints = points.slice(1, -1);

      const res = await apiFetch("/routes", {
        method: "POST",
        body: JSON.stringify({
          origin: { latitude: origin.latitude, longitude: origin.longitude },
          waypoints: waypoints.map((p) => ({ latitude: p.latitude, longitude: p.longitude })),
          destination: { latitude: destination.latitude, longitude: destination.longitude },
          mode: "drive",
        }),
      });

      if (!res.ok) {
        throw new Error("Не удалось рассчитать маршрут инженера");
      }

      const data = await res.json();
      return {
        id: `worker-route-${selectedWorker.id}`,
        workerId: selectedWorker.id,
        worker_id: selectedWorker.id,
        workerName: [selectedWorker.name, selectedWorker.surname].filter(Boolean).join(" "),
        distanceKm: (data.distance_meters / 1000).toFixed(1),
        durationMin: Math.max(1, Math.round(data.duration_seconds / 60)),
        geometry: data.geometry,
        stops: points,
        color: "#FFC800",
        raw: data,
      };
    },
    staleTime: 5 * 60 * 1000,
  });

  return {
    workerRoute: query.data || null,
    isLoadingWorkerRoute: query.isLoading,
    sortedTasks,
    points,
  };
}
