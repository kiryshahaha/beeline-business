"use client";

import React, { useState } from "react";
import Image from "next/image";
import styles from "./page.module.css";
import Search from "@/components/Search/Search";
import SmallStatsCard from "@/components/dashboard/SmallStatsCard/SmallStatsCard";
import BrigadesWorkloadCard from "@/components/dashboard/BrigadesWorkloadCard/BrigadesWorkloadCard";
import RecentActivityCard from "@/components/dashboard/RecentActivityCard/RecentActivityCard";
import ReportsExportSection from "@/components/dashboard/ReportsExportSection/ReportsExportSection";
import EmptyDataModal from "@/components/dashboard/EmptyDataModal/EmptyDataModal";
import { useFastStats } from "@/hooks/useFastStats";
import { useTicketsSummary } from "@/hooks/useTicketsSummary";

const MONTH_NAMES = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
];

function formatUpdateDate(timestamp) {
    if (!timestamp) return "";
    const date = new Date(timestamp);
    const day = date.getDate();
    const month = MONTH_NAMES[date.getMonth()];
    const hours = date.getHours().toString().padStart(2, "0");
    const minutes = date.getMinutes().toString().padStart(2, "0");
    return `${day} ${month}, ${hours}:${minutes}`;
}

function extractHoursMinutes(timestamp) {
    if (!timestamp) return "14:32";
    const date = new Date(timestamp);
    const hours = date.getHours().toString().padStart(2, "0");
    const minutes = date.getMinutes().toString().padStart(2, "0");
    return `${hours}:${minutes}`;
}

const Dashboard = () => {
    const [manualOpenModal, setManualOpenModal] = useState(false);
    const [isDismissed, setIsDismissed] = useState(false);

    const { stats, dataUpdatedAt: statsUpdatedAt, refetch: refetchStats, isLoading: isStatsLoading } = useFastStats();
    const { summary, summaryData } = useTicketsSummary();
    const isSummaryLoading = summaryData.isLoading;

    // Общий обработчик обновления
    const handleRefetch = () => {
        refetchStats();
        summaryData.refetch();
    };

    // Проверка на отсутствие данных в БД (производное состояние)
    const hasData =
        (summary?.created_in_period || 0) > 0 ||
        (summary?.open || 0) > 0 ||
        (summary?.completed_in_period || 0) > 0 ||
        (stats?.total_tickets || 0) > 0;

    const isDbEmpty = !isSummaryLoading && summaryData.isSuccess && !hasData;
    const isUploadModalOpen = manualOpenModal || (isDbEmpty && !isDismissed);

    const handleCloseModal = () => {
        setIsDismissed(true);
        setManualOpenModal(false);
    };

    // Выбираем самое свежее время обновления
    const latestUpdate = Math.max(statsUpdatedAt || 0, summaryData?.dataUpdatedAt || 0);
    const formattedDate = latestUpdate ? formatUpdateDate(latestUpdate) : "28 сентября, 14:32";
    const currentTime = latestUpdate ? extractHoursMinutes(latestUpdate) : "14:32";

    const avgDelay = stats?.average_delay_minutes || 0;
    const isWarn = avgDelay > 0 || (stats?.at_risk_tickets_count || 0) > 0;
    const slaText = isWarn ? `SLA WARN — ${avgDelay}M` : "SLA OK";
    const slaColor = isWarn ? "#FFCC00" : "#34C759";

    // Реальные данные из бэкенда
    const totalTickets = summary?.created_in_period ?? 0;
    const completedTickets = summary?.completed_in_period ?? 0;
    const completedPercent =
        totalTickets > 0
            ? Math.round((completedTickets / totalTickets) * 100)
            : 0;

    // Просроченные или требующие внимания заявки
    const atRiskCount = stats?.at_risk_tickets_count ?? 0;

    return (
        <div className={styles.container}>
            {/* Верхняя панель */}
            <div className={styles.topPanel}>
                <div className={styles.searchGroup}>
                    <Search />
                    <button
                        type="button"
                        className={styles.refreshBtn}
                        onClick={handleRefetch}
                        title="Обновить данные"
                        aria-label="Обновить данные"
                    >
                        <Image src="/icons/refresh-cw.svg" alt="Refresh" width={16} height={16} />
                    </button>

                    <button
                        type="button"
                        className={styles.importBtn}
                        onClick={() => setManualOpenModal(true)}
                        title="Загрузить данные"
                    >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="17 8 12 3 7 8"></polyline>
                            <line x1="12" y1="3" x2="12" y2="15"></line>
                        </svg>
                        <span>Загрузить CSV</span>
                    </button>
                </div>

                <div className={styles.statusGroup}>
                    {!isStatsLoading && (
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

            {/* Основная сетка страницы Dashboard Grid */}
            <div className={styles.dashboardGrid}>
                {/* 1. Верхние карточки KPI (3 штуки, по 4 колонки) */}
                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Всего заявок"
                        num={totalTickets}
                        trend="-8,4%"
                        trendType="neutral"
                        svg="/icons/tasksSum.svg"
                        footer="За текущий период"
                        loading={isSummaryLoading}
                    />
                </div>

                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Выполнено"
                        num={completedTickets}
                        trend="+12,6%"
                        trendType="positive"
                        svg="/icons/comletedTasks.svg"
                        footer={`${completedPercent}% от всех заявок за период`}
                        loading={isSummaryLoading}
                    />
                </div>

                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Просрочено"
                        num={atRiskCount}
                        trend="+3"
                        trendType="negative"
                        svg="/icons/expiredTasks.svg"
                        footer={`${atRiskCount} заявок требуют внимания`}
                        loading={isStatsLoading}
                    />
                </div>

                {/* 2. Средний ряд: Загрузка бригад (7 колонок) */}
                <div className={styles.workloadCol}>
                    <BrigadesWorkloadCard
                        onUploadClick={() => setManualOpenModal(true)}
                    />
                </div>

                {/* 3. Средний ряд: Последние события (5 колонок) */}
                <div className={styles.activityCol}>
                    <RecentActivityCard
                        onUploadClick={() => setManualOpenModal(true)}
                    />
                </div>

                {/* 4. Нижний блок: Выгрузка отчётов (12 колонок) */}
                <div className={styles.reportsCol}>
                    <ReportsExportSection currentTime={currentTime} />
                </div>
            </div>

            {/* Модальное окно загрузки данных при пустой БД или клике на кнопку */}
            <EmptyDataModal
                isOpen={isUploadModalOpen}
                onClose={handleCloseModal}
            />
        </div>
    );
};

export default Dashboard;