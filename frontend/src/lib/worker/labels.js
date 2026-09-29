// frontend/src/lib/worker/labels.js

export const STATE_LABELS = {
  assigned: "Назначена",
  dispatched: "Отправлена",
  en_route: "В пути",
  in_progress: "В работе",
  completed: "Выполнена",
  cancelled: "Отменена",
  waiting_assignment: "В очереди",
};

export const STATE_COLORS = {
  assigned: { bg: "rgba(59, 130, 246, 0.15)", text: "#60a5fa", border: "rgba(59, 130, 246, 0.3)" },
  dispatched: { bg: "rgba(99, 102, 241, 0.15)", text: "#818cf8", border: "rgba(99, 102, 241, 0.3)" },
  en_route: { bg: "rgba(245, 158, 11, 0.15)", text: "#fbbf24", border: "rgba(245, 158, 11, 0.3)" },
  in_progress: { bg: "rgba(16, 185, 129, 0.15)", text: "#34d399", border: "rgba(16, 185, 129, 0.3)" },
  completed: { bg: "rgba(107, 114, 128, 0.15)", text: "#9ca3af", border: "rgba(107, 114, 128, 0.3)" },
  pending_review: { bg: "rgba(234, 88, 12, 0.15)", text: "#fb923c", border: "rgba(234, 88, 12, 0.3)" },
  cancelled: { bg: "rgba(239, 68, 68, 0.15)", text: "#f87171", border: "rgba(239, 68, 68, 0.3)" },
};

export function getTicketStateBadge(ticket) {
  if (ticket.state === "completed") {
    if (ticket.completion_review?.state === "pending") {
      return {
        label: "Ждёт подтверждения",
        color: STATE_COLORS.pending_review,
        isPendingReview: true,
      };
    }
    return {
      label: "Выполнена",
      color: STATE_COLORS.completed,
    };
  }
  return {
    label: STATE_LABELS[ticket.state] || ticket.state || "—",
    color: STATE_COLORS[ticket.state] || STATE_COLORS.assigned,
  };
}

export const CHANGE_KIND_LABELS = {
  assigned: "Назначена вам",
  unassigned: "Снята с вас",
  reassigned: "Передана другому исполнителю",
  rescheduled: "Перенесена",
  window_changed: "Изменено окно визита",
  redirected: "Перенаправление",
  delayed: "Задержка",
  problem_reported: "Сообщена проблема",
  cancelled: "Отменена",
  reopened: "Возвращена в работу",
  completed: "Отмечена выполненной",
  completion_confirmed: "Выполнение подтверждено",
  completion_rejected: "Диспетчер вернул заявку",
};

export const CHANGE_SOURCE_LABELS = {
  planner: "планировщик",
  dispatcher: "диспетчер",
  worker: "вы",
};

export const PROBLEM_TYPES = [
  { code: "client_absent", label: "Клиента нет на месте" },
  { code: "no_access", label: "Нет доступа" },
  { code: "client_refused", label: "Клиент отказался" },
  { code: "no_equipment", label: "Не хватает оборудования" },
  { code: "need_help", label: "Нужна помощь" },
  { code: "other", label: "Другое" },
];

export const PROBLEM_TYPE_LABELS = Object.fromEntries(
  PROBLEM_TYPES.map((p) => [p.code, p.label])
);

export const ASSISTANT_SOURCE_LABELS = {
  facts: "по данным системы",
  knowledge: "со справкой по теме",
  model: "ответ модели",
};

export const TRANSPORT_TYPE_LABELS = {
  foot: "Пешком",
  bicycle: "Велосипед",
  public: "Общественный транспорт",
  auto: "Автомобиль",
  motorcycle: "Мотоцикл",
  scooter: "Самокат",
};
