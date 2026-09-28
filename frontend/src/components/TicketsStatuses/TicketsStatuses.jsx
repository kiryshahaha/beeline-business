"use client"

import { useState, useRef, useMemo } from "react"
import { useQueryClient } from "@tanstack/react-query"
import styles from "./TicketsStatuses.module.css"
import Status from "./Status"
import { useClickOutside } from "@/hooks/useClickOutside"
import { useTickets } from "@/hooks/useTickets"
import { useBrigades } from "@/hooks/useBrigades"
import { useAuth } from "@/providers/AuthProvider"
import { apiFetch } from "@/lib/apiFetch"

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

const tokenRole = (token) => {
    try {
        const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
        const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")));
        return payload.role;
    } catch {
        return null;
    }
};

const TicketsStatuses = () => {
    const { tickets, ticketsData } = useTickets({ limit: 100 });
    const { brigades = [] } = useBrigades();
    const { token } = useAuth();
    const queryClient = useQueryClient();
    const [isOpen, setIsOpen] = useState(false);
    const [activeFilter, setActiveFilter] = useState("all");
    const [savingTicketId, setSavingTicketId] = useState(null);
    const [brigadeErrors, setBrigadeErrors] = useState({});
    const containerRef = useRef(null);
    const isObserver = useMemo(() => tokenRole(token || "") === "observer", [token]);

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

    const updateBrigade = async (ticket, value) => {
        const brigadeId = value === "clear" ? null : Number(value);
        setSavingTicketId(ticket.id);
        setBrigadeErrors((errors) => ({ ...errors, [ticket.id]: null }));
        try {
            const response = await apiFetch(`/tickets/${ticket.id}/brigade`, {
                method: "PUT",
                body: JSON.stringify({ brigade_id: brigadeId }),
            });
            if (!response.ok) {
                const body = await response.json().catch(() => null);
                throw new Error(typeof body?.detail === "string" ? body.detail : "Не удалось выбрать бригаду");
            }
            await queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
        } catch (error) {
            setBrigadeErrors((errors) => ({ ...errors, [ticket.id]: error.message }));
        } finally {
            setSavingTicketId(null);
        }
    };

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
                                <div className={styles.ticketArea}>
                                    Район: {t.district || t.location?.district || "не определён"}
                                    {t.brigade_id && ` · Бригада: ${brigades.find((item) => item.id === t.brigade_id)?.name || t.brigade_id}`}
                                </div>
                                {isObserver && !t.assigned_worker_id && !t.brigade_id && brigades.some((item) => item.service_area_id === t.service_area_id) && (
                                    <label className={styles.brigadePicker}>
                                        <span>Выбрать бригаду</span>
                                        <select
                                            aria-label={`Бригада заявки ${t.id}`}
                                            value=""
                                            disabled={savingTicketId === t.id}
                                            onChange={(event) => updateBrigade(t, event.target.value)}
                                        >
                                            <option value="" disabled>Выберите бригаду</option>
                                            {brigades
                                                .filter((item) => item.service_area_id === t.service_area_id)
                                                .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                                        </select>
                                        {brigadeErrors[t.id] && <span className={styles.brigadeError}>{brigadeErrors[t.id]}</span>}
                                    </label>
                                )}
                                {isObserver && !t.assigned_worker_id && t.brigade_id && brigades.some((item) => item.id === t.brigade_id) && (
                                    <label className={styles.brigadePicker}>
                                        <span>Бригада</span>
                                        <select
                                            aria-label={`Бригада заявки ${t.id}`}
                                            value={t.brigade_id}
                                            disabled={savingTicketId === t.id}
                                            onChange={(event) => updateBrigade(t, event.target.value)}
                                        >
                                            <option value="clear">Снять назначение</option>
                                            {brigades
                                                .filter((item) => item.service_area_id === t.service_area_id)
                                                .map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                                        </select>
                                        {brigadeErrors[t.id] && <span className={styles.brigadeError}>{brigadeErrors[t.id]}</span>}
                                    </label>
                                )}
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
