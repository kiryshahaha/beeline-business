"use client";

import Search from "@/components/Search/Search";
import Image from "next/image";
import styles from "./page.module.css";
import SmallStatsCard from "@/components/dashboard/SmallStatsCard/SmallStatsCard";
import { useFastStats } from "@/hooks/useFastStats";
import { useTicketsSummary } from "@/hooks/useTicketsSummary";
import { useState, useEffect } from "react";

const Dashboard = () => {
    const { stats, dataUpdatedAt: statsUpdatedAt, refetch: refetchStats } = useFastStats();
    const { summary, summaryData } = useTicketsSummary();
    const [formattedDate, setFormattedDate] = useState("");

    // Общий обработчик обновления
    const handleRefetch = () => {
        refetchStats();
        summaryData.refetch();
    };

    // Выбираем самое свежее время обновления
    const latestUpdate = Math.max(statsUpdatedAt || 0, summaryData.dataUpdatedAt || 0) || Date.now();

    useEffect(() => {
        const date = new Date(latestUpdate);
        const day = date.getDate();
        const monthNames = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ];
        const month = monthNames[date.getMonth()];
        const hours = date.getHours().toString().padStart(2, "0");
        const minutes = date.getMinutes().toString().padStart(2, "0");
        setFormattedDate(`${day} ${month}, ${hours}:${minutes}`);
    }, [latestUpdate]);

    const avgDelay = stats?.average_delay_minutes || 0;
    const isWarn = avgDelay > 0 || (stats?.at_risk_tickets_count || 0) > 0;
    const slaText = isWarn ? `SLA WARN — ${avgDelay}M` : "SLA OK";
    const slaColor = isWarn ? "#FFCC00" : "#34C759";

    // Вычисляем процент выполненных (защита от деления на 0)
    const totalTickets = summary?.created_in_period || 0;
    const completedTickets = summary?.completed_in_period || 0;
    const completedPercent = totalTickets > 0 ? Math.round((completedTickets / totalTickets) * 100) : 0;
    
    // Просроченные или требующие внимания заявки
    const atRiskCount = stats?.at_risk_tickets_count || 0;

    return (
        <div className={styles.container}>
            {/* Верхняя панель */}
            <div className={styles.topPanel}>
                <div className={styles.searchGroup}>
                    <Search />
                    <button className={styles.refreshBtn} onClick={handleRefetch}>
                        <Image src="/icons/refresh-cw.svg" alt="Refresh" width={16} height={16} />
                    </button>
                </div>

                <div className={styles.statusGroup}>
                    {stats && (
                        <div 
                            className={styles.slaPill} 
                            style={{ "--sla-color": slaColor }}
                        >
                            <span className={styles.slaDot}></span>
                            {slaText}
                        </div>
                    )}
                    <span className={styles.timeText}>{formattedDate}</span>
                </div>
            </div>

            <div className={styles.smallStats}>
                {/* Карточка 1: Всего заявок */}
                <SmallStatsCard
                    header="Всего заявок"
                    num={totalTickets}
                    trend="-8,4%"
                    trendType="neutral"
                    svg="/icons/tasksSum.svg"
                    footer="23 новые за последние 2 часа"
                />

                {/* Карточка 2: Выполнено */}
                <SmallStatsCard
                    header="Выполнено"
                    num={completedTickets}
                    trend="+12,6%"
                    trendType="positive"
                    svg="/icons/comletedTasks.svg"
                    footer={`${completedPercent}% от всех заявок за период`}
                />

                {/* Карточка 3: Просрочено */}
                <SmallStatsCard
                    header="Просрочено"
                    num={atRiskCount}
                    trend="+3"
                    trendType="negative"
                    svg="/icons/expiredTasks.svg"
                    footer={`${atRiskCount} заявок требуют внимания`}
                />
            </div>
        </div>
    );
};

export default Dashboard;