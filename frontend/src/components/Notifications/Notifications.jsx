import styles from "./Notifications.module.css";
import Image from "next/image";
import { useNotificationsWS } from "@/hooks/useNotificationsWS";
import { useNotificationsHistory } from "@/hooks/useNotificationsHistory";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import React, { useEffect, useState, useRef, useCallback } from "react";

const NotificationsHeader = ({ isOpen, hasUnread, onReadAll }) => {
    return (
        <div className={styles.headerContent}>
            {isOpen && (
                <button 
                    className={styles.readAllBtn}
                    onClick={(e) => {
                        e.stopPropagation();
                        onReadAll();
                    }}
                >
                    Прочитать всё
                </button>
            )}
            <div className={styles.iconWrapper}>
                <Image src="/icons/bell.svg" alt="Уведомления" width={20} height={20} />
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

    return (
        <div ref={itemRef} className={`${styles.item} ${!isRead ? styles.unread : ""}`}>
            <div className={styles.title}>
                {notif.data?.title || "Заявка №" + notif.ticket_id}
            </div>
            <div className={styles.body}>
                {notif.kind === "TICKET_ASSIGNED" 
                    ? "Новая заявка назначена"
                    : notif.data?.status 
                        ? `Статус: ${notif.data.status}` 
                        : "Новая заявка назначена"}
            </div>
            <div className={styles.time}>
                {new Date(notif.created_at).toLocaleString('ru-RU', {
                    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
                })}
            </div>
        </div>
    );
};

const Notifications = () => {
    const { hasUnread, clearUnread } = useNotificationsWS();
    const { notifications, isLoading } = useNotificationsHistory();
    const [readIds, setReadIds] = useState(new Set());

    // When new notifications arrive, we clear the red dot if they all get read
    // But since the server doesn't track read state, we'll just track locally.

    const markAsRead = useCallback((id) => {
        setReadIds(prev => {
            if (prev.has(id)) return prev;
            const next = new Set(prev);
            next.add(id);
            return next;
        });
    }, []);

    const handleReadAll = () => {
        if (notifications) {
            setReadIds(new Set(notifications.map(n => n.id)));
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
            <div className={styles.list}>
                {isLoading ? (
                    <div className={styles.empty}>Загрузка...</div>
                ) : notifications?.length === 0 ? (
                    <div className={styles.empty}>Нет уведомлений</div>
                ) : (
                    notifications?.map(notif => (
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