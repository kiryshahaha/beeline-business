"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Определение начальной точки: предыдущая заявка этого же инженера (или предыдущая в списке / офис)
 */
export function findPreviousPointForTicket(
  currentTicket,
  allTickets = [],
  allWorkers = []
) {
  if (!currentTicket?.location?.latitude || !currentTicket?.location?.longitude) {
    return null;
  }

  // Маршрут строится ТОЛЬКО для назначенной заявки, от реальной предыдущей таски инженера
  const workerId = currentTicket.assigned_worker_id;
  if (!workerId) {
    return null;
  }

  // Ищем все таски этого конкретного инженера с валидными координатами
  const workerTickets = allTickets
    .filter((t) => (
      t.assigned_worker_id === workerId &&
      t.location?.latitude != null &&
      t.location?.longitude != null
    ))
    .sort((a, b) => {
      // 1. По фактическому времени выполнения (если выполнена)
      if (a.actual_completed_at && b.actual_completed_at) {
        return new Date(a.actual_completed_at).getTime() - new Date(b.actual_completed_at).getTime();
      }
      if (a.actual_completed_at) return -1;
      if (b.actual_completed_at) return 1;

      // 2. По запланированному времени визита
      const timeA = new Date(a.planned_start_at || a.visit_window_start || 0).getTime();
      const timeB = new Date(b.planned_start_at || b.visit_window_start || 0).getTime();
      if (timeA !== timeB) return timeA - timeB;
      return a.id - b.id;
    });

  const currentIndex = workerTickets.findIndex((t) => t.id === currentTicket.id);

  // Если у инженера есть предшествующая задача в цепочке — строим маршрут от неё
  if (currentIndex > 0) {
    const prevTicket = workerTickets[currentIndex - 1];
    return {
      type: "ticket",
      id: prevTicket.id,
      latitude: Number(prevTicket.location.latitude),
      longitude: Number(prevTicket.location.longitude),
      label: `Заявка #${prevTicket.id} · ${prevTicket.title || "Предыдущая задача"}`,
      address: prevTicket.location?.address || prevTicket.title,
    };
  }

  // Если текущая задача не найдена в списке, но у инженера есть другие задачи — берём последнюю выполненную или запланированную
  if (currentIndex === -1 && workerTickets.length > 0) {
    const prevTicket = workerTickets[workerTickets.length - 1];
    return {
      type: "ticket",
      id: prevTicket.id,
      latitude: Number(prevTicket.location.latitude),
      longitude: Number(prevTicket.location.longitude),
      label: `Заявка #${prevTicket.id} · ${prevTicket.title || "Предыдущая задача"}`,
      address: prevTicket.location?.address || prevTicket.title,
    };
  }

  // Если это первая заявка инженера — берём точку выезда инженера (база / офис)
  const worker = allWorkers.find((w) => w.id === workerId);
  if (worker?.location?.latitude && worker?.location?.longitude) {
    const workerName = [worker.surname, worker.name].filter(Boolean).join(" ") || `Инженер #${worker.id}`;
    return {
      type: "worker",
      id: worker.id,
      latitude: Number(worker.location.latitude),
      longitude: Number(worker.location.longitude),
      label: `Точка выезда (${workerName})`,
      address: worker.location?.address || worker.brigade_name || "Место старта смены",
    };
  }

  return null;
}

/**
 * Хук для расчета актуального дорожного маршрута от предыдущей точки к выбранной таске
 */
export function useTicketRouteLeg(
  selectedTicket,
  allTickets = [],
  allWorkers = []
) {
  const { token } = useAuth();

  const prevPoint = selectedTicket
    ? findPreviousPointForTicket(selectedTicket, allTickets, allWorkers)
    : null;

  const destPoint =
    selectedTicket?.location?.latitude && selectedTicket?.location?.longitude
      ? {
          type: "ticket",
          id: selectedTicket.id,
          latitude: Number(selectedTicket.location.latitude),
          longitude: Number(selectedTicket.location.longitude),
          label: `Заявка #${selectedTicket.id}`,
          address: selectedTicket.location?.address || selectedTicket.title,
        }
      : null;

  const queryKey = [
    "ticketRouteLeg",
    selectedTicket?.id,
    prevPoint?.latitude,
    prevPoint?.longitude,
    destPoint?.latitude,
    destPoint?.longitude,
  ];

  const query = useQuery({
    queryKey,
    enabled: !!token && !!prevPoint && !!destPoint,
    queryFn: async () => {
      const res = await apiFetch("/routes", {
        method: "POST",
        body: JSON.stringify({
          origin: { latitude: prevPoint.latitude, longitude: prevPoint.longitude },
          destination: { latitude: destPoint.latitude, longitude: destPoint.longitude },
          mode: "drive",
        }),
      });

      if (!res.ok) {
        throw new Error("Не удалось рассчитать маршрут");
      }

      const data = await res.json();
      return {
        origin: prevPoint,
        destination: destPoint,
        distanceKm: (data.distance_meters / 1000).toFixed(1),
        durationMin: Math.max(1, Math.round(data.duration_seconds / 60)),
        geometry: data.geometry,
      };
    },
    staleTime: 5 * 60 * 1000,
  });

  return {
    routeLeg: query.data || null,
    isLoadingRoute: query.isLoading,
    prevPoint,
  };
}
