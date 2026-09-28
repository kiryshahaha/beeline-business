import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";

function formatTime(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

/**
 * Парсер события в структуру, готовую для отображения в дизайне ленты активности.
 */
function parseActivityItem(item, index) {
  const { kind, occurred_at, ticket, actor, details } = item;
  const ticketId = ticket?.id;
  const time = formatTime(occurred_at);

  let title = "";
  let badgeText = "Событие";
  let badgeType = "neutral";
  let badgeColor = "#8E8E93";
  let iconType = "info";

  switch (kind) {
    case "ticket_status_changed": {
      const isCompleted = details?.status === "completed" || ticket?.status === "completed";
      const isWontFix = details?.status === "wont_fix" || ticket?.status === "wont_fix";
      const isInProgress = details?.status === "in_progress" || ticket?.status === "in_progress";

      if (isCompleted) {
        badgeText = "Выполнено";
        badgeType = "success";
        badgeColor = "#34C759";
        iconType = "check";
        const actorName = actor?.full_name || details?.worker?.full_name || "Бригада";
        title = `${actorName} завершила заявку #${ticketId}`;
      } else if (isWontFix) {
        badgeText = "Отклонено";
        badgeType = "danger";
        badgeColor = "#FF3B30";
        iconType = "alert";
        title = `Заявка #${ticketId} закрыта без выполнения`;
      } else if (isInProgress) {
        badgeText = "В работе";
        badgeType = "info";
        badgeColor = "#007AFF";
        iconType = "clock";
        const actorName = actor?.full_name || details?.worker?.full_name || "Исполнитель";
        title = `${actorName} начал работу по заявке #${ticketId}`;
      } else {
        badgeText = "Статус";
        badgeType = "neutral";
        badgeColor = "#8E8E93";
        iconType = "info";
        title = `Статус заявки #${ticketId} изменён`;
      }
      break;
    }

    case "ticket_rescheduled": {
      badgeText = "Отложено";
      badgeType = "warning";
      badgeColor = "#FF9500";
      iconType = "clock";
      const reasonPart = details?.reason ? ` (${details.reason})` : "";
      title = `Заявка #${ticketId} отложена${reasonPart}`;
      break;
    }

    case "ticket_assigned":
    case "ticket_reassigned":
    case "plan_applied": {
      badgeText = "Назначение";
      badgeType = "info";
      badgeColor = "#007AFF";
      iconType = "user";
      if (details?.worker?.full_name) {
        title = `Назначен исполнитель ${details.worker.full_name} для заявки #${ticketId}`;
      } else {
        title = `Назначен исполнитель для заявки #${ticketId}`;
      }
      break;
    }

    case "ticket_unassigned": {
      badgeText = "Снято";
      badgeType = "warning";
      badgeColor = "#FF9500";
      iconType = "user";
      title = `Снято назначение с заявки #${ticketId}`;
      break;
    }

    case "ticket_delayed": {
      badgeText = "SLA";
      badgeType = "danger";
      badgeColor = "#FF3B30";
      iconType = "alert";
      title = `SLA заявки #${ticketId} перешёл в критический статус`;
      break;
    }

    case "comment_added":
    case "comment_edited": {
      badgeText = "Комментарий";
      badgeType = "purple";
      badgeColor = "#AF52DE";
      iconType = "comment";
      const author = actor?.full_name || "Диспетчер";
      title = `${author} добавил комментарий к #${ticketId}`;
      break;
    }

    case "ticket_created": {
      badgeText = "Новая";
      badgeType = "teal";
      badgeColor = "#30B0C7";
      iconType = "plus";
      const address = ticket?.title ? ` · ${ticket.title}` : "";
      title = `Создана новая заявка #${ticketId}${address}`;
      break;
    }

    case "ticket_cancelled": {
      badgeText = "Отменено";
      badgeType = "danger";
      badgeColor = "#FF3B30";
      iconType = "alert";
      title = `Заявка #${ticketId} отменена`;
      break;
    }

    default: {
      badgeText = "Инфо";
      badgeType = "neutral";
      badgeColor = "#8E8E93";
      iconType = "info";
      title = `Событие по заявке #${ticketId}`;
      break;
    }
  }

  return {
    id: `${item.kind}-${ticketId}-${item.occurred_at}-${index}`,
    raw: item,
    occurredAt: occurred_at,
    formattedTime: time,
    title,
    badgeText,
    badgeType,
    badgeColor,
    iconType,
    ticket,
    actor,
    details,
  };
}

export function useRecentActivity({ limit = 20, offset = 0 } = {}) {
  const { token } = useAuth();

  const queryInfo = useQuery({
    queryKey: ["recentActivity", limit, offset],
    enabled: !!token,
    refetchInterval: 30000, // Автообновление каждые 30 секунд ("Авто · 30 сек")

    queryFn: async () => {
      const urlParams = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });

      const res = await apiFetch(`/analytics/recent-activity?${urlParams}`);

      if (!res.ok) {
        throw new Error("Ошибка при получении ленты событий");
      }

      return res.json();
    },
  });

  const rawEvents = queryInfo.data || [];
  const events = rawEvents.map(parseActivityItem);

  return {
    events,
    ...queryInfo,
  };
}
