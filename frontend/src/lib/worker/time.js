// frontend/src/lib/worker/time.js

const MOSCOW_TZ = "Europe/Moscow";

/**
 * Returns today's date string in YYYY-MM-DD in Europe/Moscow
 */
export function getTodayMsk() {
  const d = new Date();
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: MOSCOW_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/**
 * Returns tomorrow's date string in YYYY-MM-DD in Europe/Moscow
 */
export function getTomorrowMsk() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: MOSCOW_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/**
 * Formats date string "YYYY-MM-DD" as "29 сент."
 */
export function formatMskDayMonth(dateStr) {
  if (!dateStr) return "";
  try {
    const [y, m, d] = dateStr.split("-").map(Number);
    const dateObj = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: MOSCOW_TZ,
      day: "numeric",
      month: "short",
    }).format(dateObj);
  } catch {
    return dateStr;
  }
}

/**
 * Formats time as HH:MM in Moscow time zone
 */
export function formatMskTime(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: MOSCOW_TZ,
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return "";
  }
}

/**
 * Formats date and time as "D MMM, HH:MM" in Moscow time zone
 */
export function formatMskDateTime(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: MOSCOW_TZ,
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return "";
  }
}

/**
 * Formats date as "D MMMM" or "D MMMM YYYY" in Moscow time zone
 */
export function formatMskDateFull(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: MOSCOW_TZ,
      day: "numeric",
      month: "long",
    }).format(d);
  } catch {
    return "";
  }
}

/**
 * Calculates duration in minutes from start until end (or now)
 */
export function calcDurationMinutes(startIso, endIso = null) {
  if (!startIso) return 0;
  try {
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const diffMs = end - start;
    return Math.max(0, Math.round(diffMs / (1000 * 60)));
  } catch {
    return 0;
  }
}

/**
 * Adds minutes to current date and returns ISO string
 */
export function getFutureTimeIso(minutes) {
  const d = new Date(Date.now() + minutes * 60 * 1000);
  return d.toISOString();
}
