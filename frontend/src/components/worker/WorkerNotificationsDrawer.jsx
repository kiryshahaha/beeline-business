// frontend/src/components/worker/WorkerNotificationsDrawer.jsx
"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNotifications } from "@/lib/worker/api";
import { formatMskDateTime } from "@/lib/worker/time";
import { useAuth } from "@/providers/AuthProvider";
import styles from "./WorkerNotificationsDrawer.module.css";

const NOTIF_TITLES = {
  ticket_assigned: "Назначена заявка",
  ticket_unassigned: "Снята заявка",
  ticket_rescheduled: "Перенос заявки",
  ticket_window_changed: "Изменение окна визита",
  ticket_completion_confirmed: "Выполнение подтверждено",
  ticket_completion_rejected: "Выполнение отклонено",
  ticket_problem_reported: "Сообщено о проблеме",
  ticket_delay_reported: "Сообщено о задержке",
};

export default function WorkerNotificationsDrawer({ isOpen, onClose }) {
  const { user } = useAuth();
  const storageKey = user ? `worker_read_notifs_${user.id}` : "worker_read_notifs";

  const [readIds, setReadIds] = useState(() => {
    if (typeof window === "undefined") return new Set();
    try {
      const raw = localStorage.getItem(storageKey);
      return raw ? new Set(JSON.parse(raw)) : new Set();
    } catch {
      return new Set();
    }
  });

  const { data: notifications = [], isLoading, refetch } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => fetchNotifications(20),
    enabled: isOpen,
    staleTime: 5000,
  });

  const markAllAsRead = useCallback(() => {
    if (notifications.length > 0) {
      const allIds = new Set([...readIds, ...notifications.map((n) => n.id)]);
      setReadIds(allIds);
      try {
        localStorage.setItem(storageKey, JSON.stringify([...allIds]));
      } catch {
        // ignore
      }
    }
  }, [notifications, readIds, storageKey]);

  useEffect(() => {
    if (isOpen && notifications.length > 0) {
      // Auto mark as read on drawer open after a slight delay
      const timer = setTimeout(markAllAsRead, 1500);
      return () => clearTimeout(timer);
    }
  }, [isOpen, notifications, markAllAsRead]);

  if (!isOpen) return null;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.drawer} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleRow}>
            <h3 className={styles.title}>Уведомления</h3>
            {notifications.length > 0 && (
              <button
                type="button"
                className={styles.readAllBtn}
                onClick={markAllAsRead}
              >
                Прочитать все
              </button>
            )}
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Закрыть">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className={styles.content}>
          {isLoading && (
            <div className={styles.loading}>Загрузка уведомлений...</div>
          )}

          {!isLoading && notifications.length === 0 && (
            <div className={styles.empty}>Новых уведомлений нет</div>
          )}

          {!isLoading &&
            notifications.map((n) => {
              const kind = (n.kind || "").toLowerCase();
              const title = NOTIF_TITLES[kind] || n.data?.title || `Событие #${n.id}`;
              const isRead = readIds.has(n.id);

              let detail = "";
              if (kind === "ticket_assigned") {
                detail = n.data?.title ? `№${n.ticket_id}: ${n.data.title}` : `№${n.ticket_id}`;
              } else if (kind === "ticket_unassigned") {
                detail = `№${n.ticket_id} — ${n.data?.reason_text || n.data?.reason || "причина не указана"}`;
              } else if (kind === "ticket_completion_rejected") {
                detail = `№${n.ticket_id} — ${n.data?.reason || "причина не указана"}`;
              } else if (kind === "ticket_completion_confirmed") {
                detail = `№${n.ticket_id} — Выполнение одобрено диспетчером`;
              } else if (kind === "ticket_problem_reported") {
                detail = `№${n.ticket_id} — ${n.data?.text || ""}`;
              } else if (kind === "ticket_delay_reported") {
                detail = `№${n.ticket_id} — ${n.data?.reason || ""}`;
              } else {
                detail = n.data?.reason_text || n.data?.note || n.data?.message || "";
              }

              return (
                <div
                  key={n.id}
                  className={`${styles.notifItem} ${!isRead ? styles.unread : ""}`}
                >
                  <div className={styles.itemHeader}>
                    <span className={styles.itemTitle}>{title}</span>
                    <span className={styles.itemTime}>
                      {formatMskDateTime(n.created_at)}
                    </span>
                  </div>
                  {detail && <div className={styles.itemDetail}>{detail}</div>}
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
