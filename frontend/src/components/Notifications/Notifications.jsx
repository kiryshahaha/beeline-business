"use client";

import styles from "./Notifications.module.css";
import { useNotificationsWS } from "@/hooks/useNotificationsWS";
import { useNotificationsHistory } from "@/hooks/useNotificationsHistory";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import React, { useEffect, useState, useRef, useCallback } from "react";

const NOTIFICATION_LABELS = {
    ticket_assigned: "Назначена заявка",
    ticket_status_changed: "Статус заявки изменен",
    ticket_unassigned: "Снято назначение с заявки",
    ticket_rescheduled: "Перенесено время заявки",
    ticket_window_changed: "Изменено окно визита",
    ticket_completion_confirmed: "Выполнение подтверждено",
    ticket_completion_rejected: "Выполнение отклонено",
    ticket_completion_requested: "Запрошено подтверждение завершения",
    ticket_delay_reported: "Сообщено о задержке выполнения",
    ticket_problem_reported: "Сообщено о проблеме на объекте",
    TICKET_ASSIGNED: "Назначена заявка",
};

const STATUS_TEXT = {
    planned: "Ожидает",
    in_progress: "В работе",
    completed: "Выполнена",
    wont_fix: "Отменена",
};

const NotificationsHeader = ({ isOpen, hasUnread, onReadAll }) => {
    return (
        <div className={styles.headerContent}>
            {isOpen && (
                <button 
                    type="button"
                    className={styles.readAllBtn}
                    onClick={(e) => {
                        e.stopPropagation();
                        onReadAll();
                    }}
                >
                    Прочитать всё
                </button>
            )}
            <div className={styles.iconWrapper} title="Уведомления">
                <div className={styles.bellIcon} aria-label="Уведомления" />
                {hasUnread && <div className={styles.unreadBadge} />}
            </div>
        </div>
    );
};

const NotificationItem = ({ notif, isRead, markAsRead }) => {
    const itemRef = useRef(null);

    useEffect(() => {
        if (isRead) return;

        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting) {
                markAsRead(notif.id);
            }
        }, {
            threshold: 0.5
        });

        if (itemRef.current) {
            observer.observe(itemRef.current);
        }

        return () => observer.disconnect();
    }, [isRead, markAsRead, notif.id]);

    const kindLabel = NOTIFICATION_LABELS[notif.kind] || "Уведомление по заявке";
    const statusLabel = notif.data?.status ? (STATUS_TEXT[notif.data.status] || notif.data.status) : null;

    return (
        <div ref={itemRef} className={`${styles.item} ${!isRead ? styles.unread : ""}`}>
            <div className={styles.title}>
                {notif.data?.title || (notif.ticket_id ? `Заявка #${notif.ticket_id}` : "Событие системы")}
            </div>
            <div className={styles.body}>
                {kindLabel}
                {statusLabel ? ` · Статус: ${statusLabel}` : ""}
                {notif.data?.note ? ` («${notif.data.note}»)` : ""}
            </div>
            <div className={styles.time}>
                {new Date(notif.created_at).toLocaleString('ru-RU', {
                    timeZone: "Europe/Moscow",
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit'
                })}
            </div>
        </div>
    );
};

const Notifications = () => {
    const { hasUnread, clearUnread } = useNotificationsWS();
    const { notifications = [] } = useNotificationsHistory();
    const [readIds, setReadIds] = useState(() => {
        if (typeof window === "undefined") return new Set();
        try {
            const raw = localStorage.getItem("beeline_read_notification_ids");
            return raw ? new Set(JSON.parse(raw)) : new Set();
        } catch {
            return new Set();
        }
    });

    const markAsRead = useCallback((id) => {
        setReadIds((prev) => {
            if (prev.has(id)) return prev;
            const next = new Set(prev);
            next.add(id);
            try {
                localStorage.setItem("beeline_read_notification_ids", JSON.stringify([...next]));
            } catch {
                // ignore
            }
            return next;
        });
    }, []);

    const handleReadAll = () => {
        if (notifications.length > 0) {
            const allIds = new Set([...readIds, ...notifications.map((n) => n.id)]);
            setReadIds(allIds);
            try {
                localStorage.setItem("beeline_read_notification_ids", JSON.stringify([...allIds]));
            } catch {
                // ignore
            }
        }
        clearUnread();
    };

    return (
        <ExpandableMenu
            baseSize={42}
            className={styles.menuOverride}
            renderHeader={({ isOpen }) => (
                <NotificationsHeader 
                    isOpen={isOpen} 
                    hasUnread={hasUnread} 
                    onReadAll={handleReadAll} 
                />
            )}
        >
            <div className={styles.content}>
                {notifications.length === 0 ? (
                    <div className={styles.empty}>Нет новых уведомлений</div>
                ) : (
                    notifications.map((notif) => (
                        <NotificationItem
                            key={notif.id}
                            notif={notif}
                            isRead={readIds.has(notif.id)}
                            markAsRead={markAsRead}
                        />
                    ))
                )}
            </div>
        </ExpandableMenu>
    );
};

export default Notifications;