/**
 * Утилиты для расчета метрик маршрута, времени смены и форматирования адресов.
 */

export function getHaversineDistanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371; // Earth radius in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export function calculateRouteDistanceKm(route) {
  if (!route) return "0.0";

  // 1. Проверяем legs в GeoJSON (от Geoapify / OSRM бэкенда)
  const features = route.raw?.geojson?.features || route.geojson?.features || [];
  const pathFeature = features.find(
    (f) =>
      (f.geometry?.type === "LineString" || f.geometry?.type === "MultiLineString") &&
      f.properties?.legs?.length,
  );

  if (pathFeature?.properties?.legs) {
    const totalMeters = pathFeature.properties.legs.reduce(
      (sum, leg) => sum + (leg.distance_meters || 0),
      0,
    );
    if (totalMeters > 0) {
      return (totalMeters / 1000).toFixed(1);
    }
  }

  // 2. Расчет по координатам линии дорог (allCoordinates)
  const coords = route.allCoordinates || [];
  if (coords.length >= 2) {
    let distKm = 0;
    for (let i = 0; i < coords.length - 1; i++) {
      const [lon1, lat1] = coords[i];
      const [lon2, lat2] = coords[i + 1];
      if (
        Number.isFinite(lon1) &&
        Number.isFinite(lat1) &&
        Number.isFinite(lon2) &&
        Number.isFinite(lat2)
      ) {
        distKm += getHaversineDistanceKm(lat1, lon1, lat2, lon2);
      }
    }
    return distKm.toFixed(1);
  }

  // 3. Fallback: по остановкам
  const stops = route.stops || [];
  if (stops.length >= 2) {
    let distKm = 0;
    for (let i = 0; i < stops.length - 1; i++) {
      distKm += getHaversineDistanceKm(
        stops[i].latitude,
        stops[i].longitude,
        stops[i + 1].latitude,
        stops[i + 1].longitude,
      );
    }
    // Умножаем на дорожный коэффициент извилистости ~1.3
    return (distKm * 1.3).toFixed(1);
  }

  return "0.0";
}

export function formatTime(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function calculateShiftTimings(stops = []) {
  if (!stops || stops.length === 0) {
    return {
      timeRange: "09:00 — 18:00",
      totalDurationHours: "~9 ч",
    };
  }

  const first = stops[0];
  const last = stops[stops.length - 1];

  const startTimeStr = first.arrival_at || first.service_start_at;
  const endTimeStr = last.service_end_at || last.arrival_at;

  const startFormatted = formatTime(startTimeStr) || "09:00";
  const endFormatted = formatTime(endTimeStr) || (stops.length > 3 ? "17:30" : "14:00");

  let totalDurationHours = "";
  if (startTimeStr && endTimeStr) {
    const s = new Date(startTimeStr).getTime();
    const e = new Date(endTimeStr).getTime();
    if (!isNaN(s) && !isNaN(e) && e > s) {
      const diffMinutes = Math.round((e - s) / 60000);
      const hours = Math.floor(diffMinutes / 60);
      const mins = diffMinutes % 60;
      totalDurationHours = hours > 0 ? `${hours}ч ${mins > 0 ? `${mins}м` : ""}` : `${mins}м`;
    }
  }

  if (!totalDurationHours) {
    totalDurationHours = `~${Math.min(9, Math.max(3, stops.length * 1.2)).toFixed(1)} ч`;
  }

  return {
    timeRange: `${startFormatted} — ${endFormatted}`,
    totalDurationHours,
  };
}

export function resolveStopDetails(stop, index, totalStops, tickets = [], offices = [], locationById = null) {
  const isStart = stop.sequence === 1 && !stop.ticket_id;
  const isFinish = stop.sequence === totalStops && !stop.ticket_id && totalStops > 1;

  let title = "";
  let address = "";
  let ticket = null;
  let office = null;

  if (stop.ticket_id) {
    ticket = tickets.find((t) => t.id === stop.ticket_id);
    title = ticket?.title || (ticket?.category ? `Категория: ${ticket.category}` : `Заявка #${stop.ticket_id}`);
    address =
      ticket?.location?.address ||
      locationById?.get?.(stop.location_id)?.address ||
      "Адрес объекта";
  } else {
    office = offices.find(
      (o) => o.location_id === stop.location_id || o.office_id === stop.location_id,
    );
    title = isStart
      ? "База / Выезд на смену"
      : isFinish
        ? "База / Возврат со смены"
        : office?.office_name || "Промежуточный офис / База";
    address =
      office?.address ||
      locationById?.get?.(stop.location_id)?.address ||
      "Центральный офис обслуживания";
  }

  return {
    isStart,
    isFinish,
    title,
    address,
    ticket,
    office,
    arrivalFormatted: formatTime(stop.arrival_at),
    serviceStartFormatted: formatTime(stop.service_start_at),
    serviceEndFormatted: formatTime(stop.service_end_at),
  };
}
