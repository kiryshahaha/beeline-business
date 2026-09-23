"use client"

import { useState, useRef } from "react"
import styles from "./TicketsStatuses.module.css"
import Status from "./Status"
import { useTicketsSummary } from "@/hooks/useTicketsSummary"
import { useClickOutside } from "@/hooks/useClickOutside"

const TicketsStatuses = () => {
    const { summary } = useTicketsSummary({ period: "today" });
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef(null);

    useClickOutside(containerRef, () => setIsOpen(false));

    const allCount = summary ? summary.open + summary.assigned + summary.in_progress + summary.completed : 0;
    const urgentCount = summary ? summary.open : 0; 
    const completedCount = summary ? summary.completed : 0;

    return (
        <div 
            ref={containerRef}
            className={`${styles.container} ${isOpen ? styles.expanded : ""}`}
            onClick={() => !isOpen && setIsOpen(true)}
        >
            <div className={styles.pillsWrapper}>
                <Status label="Все" count={allCount} variant="all" />
                <Status label="Срочные" count={urgentCount} variant="urgent" />
                <Status label="Выполнено" count={completedCount} variant="completed" />
            </div>
            
            {/* Сюда позже можно будет добавить контент для раскрытого состояния */}
            <div className={styles.content}>
                Здесь будет подробный список или графики...
            </div>
        </div>
    );
};

export default TicketsStatuses;