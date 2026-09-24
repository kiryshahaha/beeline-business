"use client"

import { useState, useRef } from "react"
import styles from "./TicketsStatuses.module.css"
import Status from "./Status"
import { useClickOutside } from "@/hooks/useClickOutside"
import { useTickets } from "@/hooks/useTickets"

const STATUS_LABELS = {
    planned: "Ожидание", // По макету
    in_progress: "В пути", // По макету
    completed: "Выполнено",
    wont_fix: "Отменена"
};

const ClockIcon = () => (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M7 13C10.3137 13 13 10.3137 13 7C13 3.68629 10.3137 1 7 1C3.68629 1 1 3.68629 1 7C1 10.3137 3.68629 13 7 13Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M7 3.5V7L9.33333 8.16667" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
);

const formatTime = (isoString) => {
    if (!isoString) return "";
    const d = new Date(isoString);
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

const formatTimeWindow = (start, end) => {
    if (!start || !end) return "Время не указано";
    return `${formatTime(start)} - ${formatTime(end)}`;
};

const formatAddress = (loc) => {
    if (!loc) return "Адрес не указан";
    const parts = [];
    if (loc.street) parts.push(`ул. ${loc.street}`);
    if (loc.building_number) parts.push(loc.building_number);
    if (loc.apartment) parts.push(`кв. ${loc.apartment}`);
    return parts.join(', ') || loc.address;
};

const TicketsStatuses = () => {
    const { tickets, ticketsData } = useTickets({ limit: 100 });
    const [isOpen, setIsOpen] = useState(false);
    const [activeFilter, setActiveFilter] = useState("all");
    const containerRef = useRef(null);

    useClickOutside(containerRef, () => setIsOpen(false));

    // Считаем статусы напрямую из списка загруженных тикетов, чтобы цифры сходились
    const allCount = tickets.length;
    const urgentCount = tickets.filter(t => t.status === "planned" && (!t.assignee_ids || t.assignee_ids.length === 0)).length;
    const completedCount = tickets.filter(t => t.status === "completed").length;

    const displayedTickets = tickets.filter(t => {
        if (activeFilter === "urgent") return t.status === "planned" && (!t.assignee_ids || t.assignee_ids.length === 0);
        if (activeFilter === "completed") return t.status === "completed";
        return true;
    });

    return (
        <div 
            ref={containerRef}
            className={`${styles.container} ${isOpen ? styles.expanded : ""}`}
            onClick={() => !isOpen && setIsOpen(true)}
        >
            <div className={styles.pillsWrapper}>
                <Status 
                    label="Все" 
                    count={allCount} 
                    variant="all" 
                    isInteractive={isOpen}
                    isInactive={isOpen && activeFilter !== "all"}
                    onClick={() => setActiveFilter("all")}
                />
                <Status 
                    label="Срочные" 
                    count={urgentCount} 
                    variant="urgent" 
                    isInteractive={isOpen}
                    isInactive={isOpen && activeFilter !== "urgent"}
                    onClick={() => setActiveFilter("urgent")}
                />
                <Status 
                    label="Выполнено" 
                    count={completedCount} 
                    variant="completed" 
                    isInteractive={isOpen}
                    isInactive={isOpen && activeFilter !== "completed"}
                    onClick={() => setActiveFilter("completed")}
                />
            </div>
            
            <div className={styles.content}>
                {ticketsData.isLoading ? (
                    <div style={{ padding: '20px', textAlign: 'center', opacity: 0.6 }}>Загрузка заявок...</div>
                ) : displayedTickets.length > 0 ? (
                    <ul key={activeFilter} className={styles.ticketsList}>
                        {displayedTickets.map((t, index) => (
                            <li 
                                key={t.id} 
                                className={styles.ticketCard}
                                style={{ animationDelay: `${index * 0.05}s` }}
                            >
                                <div className={styles.ticketRow}>
                                    <span className={styles.ticketName}>{t.title}</span>
                                    <div className={styles.ticketBadges}>
                                        <span className={`${styles.ticketStatusBadge} ${styles[t.status]}`}>
                                            {STATUS_LABELS[t.status] || t.status}
                                        </span>
                                    </div>
                                </div>
                                <div className={styles.ticketAddress}>
                                    {formatAddress(t.location)}
                                </div>
                                <div className={styles.ticketFooter}>
                                    <div className={styles.ticketTime}>
                                        <ClockIcon />
                                        <span>{formatTimeWindow(t.visit_window_start, t.visit_window_end)}</span>
                                    </div>
                                    <div className={styles.ticketType}>
                                        {t.work_type}
                                    </div>
                                </div>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <div style={{ padding: '20px', textAlign: 'center', opacity: 0.6 }}>Нет заявок в этой категории</div>
                )}
            </div>
        </div>
    );
};

export default TicketsStatuses;