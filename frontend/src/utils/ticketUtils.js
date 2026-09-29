/**
 * Utilities for ticket status, urgency, and formatting
 */

/**
 * Checks whether a ticket is urgent (high priority, emergency, or unassigned planned).
 * Used consistently across Map, Cluster badges, and Filter pills.
 */
export function isTicketUrgent(ticket) {
  if (!ticket) return false;
  return Boolean(
    ticket.priority === 1 ||
    ticket.category === "emergency" ||
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
};
