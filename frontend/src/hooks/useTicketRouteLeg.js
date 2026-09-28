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
  allWorkers = [],
  allOffices = []
) {
  if (!currentTicket?.location?.latitude || !currentTicket?.location?.longitude) {
    return null;
  }

  // 1. Если заявка назначена инженеру или бригаде — ищем предыдущую по времени задачу этой же группы
  const isAssigned = !!(currentTicket.assigned_worker_id || currentTicket.brigade_id);
  if (isAssigned) {
    const siblingTickets = allTickets
      .filter((t) => {
        const matches = currentTicket.assigned_worker_id
          ? t.assigned_worker_id === currentTicket.assigned_worker_id
          : t.brigade_id === currentTicket.brigade_id;
        return matches && t.location?.latitude != null && t.location?.longitude != null;
      })
      .sort((a, b) => {
        const timeA = new Date(a.planned_start_at || a.visit_window_start || a.id).getTime();
        const timeB = new Date(b.planned_start_at || b.visit_window_start || b.id).getTime();
        return timeA - timeB;
      });

    const currentIndex = siblingTickets.findIndex((t) => t.id === currentTicket.id);
    if (currentIndex > 0) {
      const prevTicket = siblingTickets[currentIndex - 1];
      return {
        type: "ticket",
        id: prevTicket.id,
        latitude: Number(prevTicket.location.latitude),
        longitude: Number(prevTicket.location.longitude),
        label: `Заявка #${prevTicket.id}`,
        address: prevTicket.location?.address || prevTicket.title,
      };
    }

    // Если это первая заявка инженера — берём его базу / офис
    if (currentTicket.assigned_worker_id) {
      const worker = allWorkers.find((w) => w.id === currentTicket.assigned_worker_id);
      if (worker?.location?.latitude && worker?.location?.longitude) {
        return {
          type: "worker",
          id: worker.id,
          latitude: Number(worker.location.latitude),
          longitude: Number(worker.location.longitude),
          label: `База (${[worker.name, worker.surname].filter(Boolean).join(" ") || `Инженер #${worker.id}`})`,
          address: worker.location?.address,
        };
      }
    }
  }

  // 2. Если нет исполнителя или это первая задача группы — берем предыдущую задачу из общего списка с координатами
  const validTickets = allTickets.filter(
    (t) => t.location?.latitude != null && t.location?.longitude != null
  );
  const generalIdx = validTickets.findIndex((t) => t.id === currentTicket.id);
  if (generalIdx > 0) {
    const prevTicket = validTickets[generalIdx - 1];
    return {
      type: "ticket",
      id: prevTicket.id,
      latitude: Number(prevTicket.location.latitude),
      longitude: Number(prevTicket.location.longitude),
      label: `Заявка #${prevTicket.id}`,
      address: prevTicket.location?.address || prevTicket.title,
    };
  }

  // 3. Фолбэк на офис обслуживания
  if (allOffices && allOffices.length > 0) {
    const office = allOffices[0];
    if (office.latitude && office.longitude) {
      return {
        type: "office",
        id: office.office_id || office.id,
        latitude: Number(office.latitude),
        longitude: Number(office.longitude),
        label: office.office_name || "Офис обслуживания",
        address: office.address,
      };
    }
  }

  // 4. Если это самый первый элемент в списке и нет офиса, но есть другие заявки — берем следующую
  if (validTickets.length > 1) {
    const fallbackTicket = validTickets.find((t) => t.id !== currentTicket.id);
    if (fallbackTicket) {
      return {
        type: "ticket",
        id: fallbackTicket.id,
        latitude: Number(fallbackTicket.location.latitude),
        longitude: Number(fallbackTicket.location.longitude),
        label: `Заявка #${fallbackTicket.id}`,
        address: fallbackTicket.location?.address || fallbackTicket.title,
      };
    }
  }

  return null;
}

/**
 * Хук для расчета актуального дорожного маршрута от предыдущей точки к выбранной таске
 */
export function useTicketRouteLeg(
  selectedTicket,
  allTickets = [],
  allWorkers = [],
  allOffices = []
) {
  const { token } = useAuth();

  const prevPoint = selectedTicket
    ? findPreviousPointForTicket(selectedTicket, allTickets, allWorkers, allOffices)
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
