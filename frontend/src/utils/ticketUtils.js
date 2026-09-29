/**
 * Utilities for ticket status, urgency, and formatting
 */

/**
 * Checks whether a ticket is urgent. Completed or cancelled tickets can never be urgent.
 */
export function isTicketUrgent(ticket) {
  if (!ticket) return false;
  // Завершённые или отменённые заявки не могут быть срочными
  if (["completed", "wont_fix", "cancelled"].includes(ticket.status)) return false;
  if (["closed", "cancelled"].includes(ticket.state)) return false;

  return Boolean(
    ticket.priority === 1 ||
    ticket.category === "emergency" ||
    ticket.status === "delayed" ||
    (ticket.status === "planned" && !ticket.assigned_worker_id)
  );
}

/**
 * Maps ticket status code to human readable Russian label
 */
export const STATUS_LABELS = {
  planned: "Ожидание",
  in_progress: "В работе",
  completed: "Выполнено",
  wont_fix: "Отменена",
  cancelled: "Отменена",
  delayed: "Перенесена",
  pending_review: "На проверке",
  suspended: "Приостановлена",
};

export const STATE_LABELS = {
  open: "Открыта",
  in_progress: "В работе",
  pending_review: "Ожидает подтверждения",
  closed: "Закрыта",
  cancelled: "Отменена",
};

/**
 * Форматирует дату/время строго в часовом поясе Europe/Moscow (FE-13)
 */
export function formatMskDateTime(dateStr, options = {}) {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    ...options,
  });
}

export function formatMskTime(dateStr) {
  return formatMskDateTime(dateStr, { hour: "2-digit", minute: "2-digit" });
}

export function formatMskDate(dateStr) {
  return formatMskDateTime(dateStr, { day: "2-digit", month: "2-digit", year: "numeric" });
}
