"use client"

import { useState, useRef } from "react"
import styles from "./TicketsStatuses.module.css"
import Status from "./Status"
import { useClickOutside } from "@/hooks/useClickOutside"
import { useTickets } from "@/hooks/useTickets"

import { isTicketUrgent, STATUS_LABELS as UTILS_STATUS_LABELS } from "@/utils/ticketUtils";

const STATUS_LABELS = {
    planned: "Ожидание",
    in_progress: "В работе",
    completed: "Выполнено",
    wont_fix: "Отменена",
    ...UTILS_STATUS_LABELS,
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

const TicketsStatuses = ({
    onFilterChange,
    onSelectTicket,
    filter,
    tickets: propTickets,
    selectedDistrict = null,
    onClearDistrict = null,
}) => {
    const { tickets: fetchedTickets, ticketsData } = useTickets({ limit: 100 });
    const tickets = propTickets ?? fetchedTickets;
    const [isOpen, setIsOpen] = useState(false);
    const [localFilter, setLocalFilter] = useState("all");
    const activeFilter = filter ?? localFilter;
    const containerRef = useRef(null);

    useClickOutside(containerRef, () => setIsOpen(false));
    const changeFilter = (nextFilter) => {
        setLocalFilter(nextFilter);
        onFilterChange?.(nextFilter);
        if (!isOpen) {
            setIsOpen(true);
        }
    };

    // Считаем статусы напрямую из переданных заявок района/поиска
    const allCount = tickets.length;
    const urgentCount = tickets.filter(isTicketUrgent).length;
    const inProgressCount = tickets.filter(t => t.status === "in_progress").length;
    const completedCount = tickets.filter(t => t.status === "completed").length;

    const displayedTickets = tickets.filter(t => {
        if (activeFilter === "urgent") return isTicketUrgent(t);
        if (activeFilter === "in_progress") return t.status === "in_progress";
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
                {selectedDistrict && (
                    <div className={styles.districtPill} title={`Выбран район: ${selectedDistrict}`}>
                        <span>{selectedDistrict}</span>
                        {onClearDistrict && (
                            <button
                                type="button"
                                className={styles.clearDistrictButton}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onClearDistrict();
                                }}
                                title="Сбросить район"
                                aria-label="Сбросить район"
                            >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                    <line x1="18" y1="6" x2="6" y2="18"></line>
                                    <line x1="6" y1="6" x2="18" y2="18"></line>
                                </svg>
                            </button>
                        )}
                    </div>
                )}
                <Status 
                    label="Все" 
                    count={allCount} 
                    variant="all" 
                    isInteractive={true}
                    isInactive={isOpen && activeFilter !== "all"}
                    onClick={() => changeFilter("all")}
                />
                <Status 
                    label="Срочные" 
                    count={urgentCount} 
                    variant="urgent" 
                    isInteractive={true}
                    isInactive={isOpen && activeFilter !== "urgent"}
                    onClick={() => changeFilter("urgent")}
                />
                <Status 
                    label="В работе" 
                    count={inProgressCount} 
                    variant="in_progress" 
                    isInteractive={true}
                    isInactive={isOpen && activeFilter !== "in_progress"}
                    onClick={() => changeFilter("in_progress")}
                />
                <Status 
                    label="Выполнено" 
                    count={completedCount} 
                    variant="completed" 
                    isInteractive={true}
                    isInactive={isOpen && activeFilter !== "completed"}
                    onClick={() => changeFilter("completed")}
                />
            </div>
            
            <div className={styles.content}>
                {ticketsData.isLoading ? (
                    <div style={{ padding: '20px', textAlign: 'center', opacity: 0.6 }}>Загрузка заявок...</div>
                ) : displayedTickets.length > 0 ? (
                    <ul key={activeFilter} className={styles.ticketsList}>
                        {displayedTickets.map((t, index) => {
                            const hasCoordinates = t.location?.latitude != null && t.location?.longitude != null;
                            return (
                            <li 
                                key={t.id} 
                                className={styles.ticketCard}
                                style={{ animationDelay: `${index * 0.05}s` }}
                                role={onSelectTicket && hasCoordinates ? "button" : undefined}
                                tabIndex={onSelectTicket && hasCoordinates ? 0 : undefined}
                                onClick={() => hasCoordinates && onSelectTicket?.(t)}
                                onKeyDown={(event) => {
                                    if (hasCoordinates && (event.key === "Enter" || event.key === " ")) {
                                        event.preventDefault();
                                        onSelectTicket?.(t);
                                    }
                                }}
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
                                        {hasCoordinates ? t.work_type : "Нет координат"}
                                    </div>
                                </div>
                            </li>
                            );
                        })}
                    </ul>
                ) : (
                    <div style={{ padding: '20px', textAlign: 'center', opacity: 0.6 }}>Нет заявок в этой категории</div>
                )}
            </div>
        </div>
    );
};

export default TicketsStatuses;