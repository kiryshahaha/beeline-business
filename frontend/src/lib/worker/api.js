// frontend/src/lib/worker/api.js
import { apiFetch } from "@/lib/apiFetch";

/**
 * Parses and formats backend API error responses
 */
export function formatApiError(data, fallback = "Не удалось выполнить действие") {
  if (!data) return fallback;
  const d = data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((e) => e.msg || e.message || JSON.stringify(e)).join("; ");
  }
  if (d && typeof d === "object") {
    if (d.code === "stale_revision" || d.code === "revision_conflict") {
      return "Данные обновились, проверьте и повторите";
    }
    if (d.code === "invalid_transition") {
      return "Действие уже недоступно";
    }
    if (d.message) return d.message;
  }
  if (data.message) return data.message;
  return fallback;
}

/**
 * Common worker action executor with Idempotency-Key
 */
export async function workerAction(path, body, idempotencyKey) {
  const headers = {};
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }

  const res = await apiFetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const errorMsg = formatApiError(data);
    const err = new Error(errorMsg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/me/day?date=YYYY-MM-DD
 */
export async function fetchMyDay(date) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  const res = await apiFetch(`/me/day${query}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить план дня"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/tickets/{id}
 */
export async function fetchTicket(ticketId) {
  const res = await apiFetch(`/tickets/${ticketId}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить данные заявки"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/tickets/{id}/changes?limit=50
 */
export async function fetchTicketChanges(ticketId, limit = 50) {
  const res = await apiFetch(`/tickets/${ticketId}/changes?limit=${limit}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить историю изменений"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/tickets/{id}/comments
 */
export async function fetchTicketComments(ticketId) {
  const res = await apiFetch(`/tickets/${ticketId}/comments`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить комментарии"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * POST /api/v1/tickets/{id}/comments
 */
export async function addTicketComment(ticketId, text) {
  const res = await apiFetch(`/tickets/${ticketId}/comments`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось отправить комментарий"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * PATCH /api/v1/tickets/{id}/comments/{comment_id}
 */
export async function updateTicketComment(ticketId, commentId, text) {
  const res = await apiFetch(`/tickets/${ticketId}/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось обновить комментарий"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/workers/{workerId}/equipment?date=YYYY-MM-DD
 */
export async function fetchWorkerEquipment(workerId, date) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  const res = await apiFetch(`/workers/${workerId}/equipment${query}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить список оборудования"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/routes?worker_id={workerId}&route_date={date}
 */
export async function fetchWorkerRoutes(workerId, routeDate) {
  const query = `?worker_id=${encodeURIComponent(workerId)}${routeDate ? `&route_date=${encodeURIComponent(routeDate)}` : ""}`;
  const res = await apiFetch(`/routes${query}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить маршрут"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * POST /api/v1/assistant/chat
 */
export async function sendAssistantChat({ message, history = [], ticket_id = null }) {
  const body = {
    message: message.trim(),
    history: history.slice(-10).map((m) => ({
      role: m.role,
      content: m.content.slice(0, 2000),
    })),
  };
  if (ticket_id) {
    body.ticket_id = Number(ticket_id);
  }

  const res = await apiFetch("/assistant/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let errorMsg = "Помощник временно недоступен";
    if (res.status === 429) {
      errorMsg = "Слишком много вопросов, подождите минуту";
    } else if (res.status === 503) {
      errorMsg = "Помощник временно недоступен";
    } else if (res.status === 404 && ticket_id) {
      errorMsg = "Заявка снята";
    } else {
      errorMsg = formatApiError(data, errorMsg);
    }
    const err = new Error(errorMsg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * GET /api/v1/schedule/calendar/token
 */
export async function fetchCalendarTokenStatus() {
  const res = await apiFetch("/schedule/calendar/token");
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось проверить статус календаря"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * POST /api/v1/schedule/calendar/token
 */
export async function issueCalendarToken() {
  const res = await apiFetch("/schedule/calendar/token", { method: "POST" });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось выпустить ссылку календаря"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/**
 * DELETE /api/v1/schedule/calendar/token
 */
export async function revokeCalendarToken() {
  const res = await apiFetch("/schedule/calendar/token", { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const data = await res.json().catch(() => null);
    const err = new Error(formatApiError(data, "Не удалось отозвать ссылку календаря"));
    err.status = res.status;
    throw err;
  }
  return true;
}

/**
 * GET /api/v1/notifications?limit=20
 */
export async function fetchNotifications(limit = 20, afterId = null) {
  let query = `?limit=${limit}`;
  if (afterId != null) {
    query += `&after_id=${afterId}`;
  }
  const res = await apiFetch(`/notifications${query}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(formatApiError(data, "Не удалось загрузить уведомления"));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}
