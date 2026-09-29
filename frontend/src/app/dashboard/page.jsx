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
import BrigadesJournalModal from "@/components/dashboard/BrigadesJournalModal/BrigadesJournalModal";
import EventsJournalModal from "@/components/dashboard/EventsJournalModal/EventsJournalModal";
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
    const [isJournalModalOpen, setIsJournalModalOpen] = useState(false);
    const [isEventsModalOpen, setIsEventsModalOpen] = useState(false);

    // Временной фильтр: по умолчанию "all" (все доступные данные в БД)
    // Пресеты: 'all' (за весь период датасета), 'today' (сегодня), 'week' (неделя), 'month' (месяц), 'custom' (конкретная дата)
    const [selectedPreset, setSelectedPreset] = useState("all");
    const [customDate, setCustomDate] = useState("2026-09-21");
    const [dashboardSearch, setDashboardSearch] = useState("");
    const [isDatePopoverOpen, setIsDatePopoverOpen] = useState(false);
    const popoverRef = React.useRef(null);

    // Закрытие поповера при клике вне его
    React.useEffect(() => {
        const handleClickOutside = (e) => {
            if (popoverRef.current && !popoverRef.current.contains(e.target)) {
                setIsDatePopoverOpen(false);
            }
        };
        if (isDatePopoverOpen) {
            document.addEventListener("mousedown", handleClickOutside);
        }
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, [isDatePopoverOpen]);

    // Определяем параметры для запросов
    const todayMsk = React.useMemo(() => {
        return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
    }, []);

    const { workloadDate, workloadDateFrom, workloadDateTo } = React.useMemo(() => {
        if (selectedPreset === "custom") {
            return { workloadDate: customDate, workloadDateFrom: undefined, workloadDateTo: undefined };
        }
        if (selectedPreset === "today") {
            return { workloadDate: todayMsk, workloadDateFrom: undefined, workloadDateTo: undefined };
        }
        if (selectedPreset === "week") {
            const [y, m, d] = todayMsk.split("-").map(Number);
            const dt = new Date(Date.UTC(y, m - 1, d));
            dt.setUTCDate(dt.getUTCDate() - 6);
            const from = dt.toISOString().slice(0, 10);
            return { workloadDate: undefined, workloadDateFrom: from, workloadDateTo: todayMsk };
        }
        if (selectedPreset === "month") {
            const [y, m, d] = todayMsk.split("-").map(Number);
            const dt = new Date(Date.UTC(y, m - 1, d));
            dt.setUTCDate(dt.getUTCDate() - 29);
            const from = dt.toISOString().slice(0, 10);
            return { workloadDate: undefined, workloadDateFrom: from, workloadDateTo: todayMsk };
        }
        // "all" - передаем undefined, чтобы бэкенд рассчитал среднее по всем дням с активностью
        return { workloadDate: undefined, workloadDateFrom: undefined, workloadDateTo: undefined };
    }, [selectedPreset, customDate, todayMsk]);

    const queryPeriod = selectedPreset === "all" ? "month" : (selectedPreset === "custom" ? "today" : selectedPreset);
    const queryDate = selectedPreset === "custom" ? customDate : undefined;

    const { stats, dataUpdatedAt: statsUpdatedAt, refetch: refetchStats, isLoading: isStatsLoading } = useFastStats();
    const { summary, summaryData } = useTicketsSummary({ period: queryPeriod, date: queryDate });
    const isSummaryLoading = summaryData.isLoading;

    // Текст выбранного периода для отображения на кнопке
    const getFilterLabel = () => {
        if (selectedPreset === "all") return "Все данные";
        if (selectedPreset === "today") return "Сегодня";
        if (selectedPreset === "week") return "Неделя";
        if (selectedPreset === "month") return "Месяц";
        if (selectedPreset === "custom" && customDate) {
            const parts = customDate.split("-");
            if (parts.length === 3) {
                return `${parseInt(parts[2], 10)} ${MONTH_NAMES[parseInt(parts[1], 10) - 1] || ""}`;
            }
            return customDate;
        }
        return "Период";
    };

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
    const fallbackMskDate = new Date().toLocaleDateString("ru-RU", {
        timeZone: "Europe/Moscow",
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
    });
    const formattedDate = latestUpdate ? formatUpdateDate(latestUpdate) : fallbackMskDate;

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

    // Среднее количество км на техника в день
    const avgKmPerWorker = stats?.avg_km_per_worker_per_day ?? 0;

    return (
        <div className={styles.container}>
            {/* Верхняя панель */}
            <div className={styles.topPanel}>
                <div className={styles.searchGroup}>
                    <Search
                        searchQuery={dashboardSearch}
                        onSearchChange={setDashboardSearch}
                        onClear={() => setDashboardSearch("")}
                    />
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

                    {/* Аккуратная кнопка выбора временного отрезка / календарик */}
                    <div className={styles.dateFilterWrapper} ref={popoverRef}>
                        <button
                            type="button"
                            className={`${styles.dateFilterBtn} ${isDatePopoverOpen ? styles.dateFilterBtnActive : ""}`}
                            onClick={() => setIsDatePopoverOpen((prev) => !prev)}
                            title="Выбрать период"
                        >
                            <span className={styles.dateFilterIcon}>
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                                    <line x1="16" y1="2" x2="16" y2="6"></line>
                                    <line x1="8" y1="2" x2="8" y2="6"></line>
                                    <line x1="3" y1="10" x2="21" y2="10"></line>
                                </svg>
                            </span>
                            <span>{getFilterLabel()}</span>
                            <span className={`${styles.dateFilterChevron} ${isDatePopoverOpen ? styles.chevronOpen : ""}`}>
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                    <polyline points="6 9 12 15 18 9"></polyline>
                                </svg>
                            </span>
                        </button>

                        {isDatePopoverOpen && (
                            <div className={styles.dateFilterPopover}>
                                <div className={styles.popoverHeader}>Временной отрезок</div>
                                <button
                                    type="button"
                                    className={`${styles.presetBtn} ${selectedPreset === "all" ? styles.presetBtnActive : ""}`}
                                    onClick={() => {
                                        setSelectedPreset("all");
                                        setIsDatePopoverOpen(false);
                                    }}
                                >
                                    <span>Все данные</span>
                                    <span className={styles.presetBadge}>Все</span>
                                </button>
                                <button
                                    type="button"
                                    className={`${styles.presetBtn} ${selectedPreset === "today" ? styles.presetBtnActive : ""}`}
                                    onClick={() => {
                                        setSelectedPreset("today");
                                        setIsDatePopoverOpen(false);
                                    }}
                                >
                                    <span>Сегодня</span>
                                    <span className={styles.presetBadge}>1 дн.</span>
                                </button>
                                <button
                                    type="button"
                                    className={`${styles.presetBtn} ${selectedPreset === "week" ? styles.presetBtnActive : ""}`}
                                    onClick={() => {
                                        setSelectedPreset("week");
                                        setIsDatePopoverOpen(false);
                                    }}
                                >
                                    <span>Неделя</span>
                                    <span className={styles.presetBadge}>7 дн.</span>
                                </button>
                                <button
                                    type="button"
                                    className={`${styles.presetBtn} ${selectedPreset === "month" ? styles.presetBtnActive : ""}`}
                                    onClick={() => {
                                        setSelectedPreset("month");
                                        setIsDatePopoverOpen(false);
                                    }}
                                >
                                    <span>Месяц</span>
                                    <span className={styles.presetBadge}>30 дн.</span>
                                </button>

                                <div className={styles.popoverDivider} />

                                <div className={styles.customDateBlock}>
                                    <span className={styles.customDateLabel}>Календарь (выбрать дату)</span>
                                    <input
                                        type="date"
                                        className={styles.customDateInput}
                                        value={customDate}
                                        onChange={(e) => {
                                            if (e.target.value) {
                                                setCustomDate(e.target.value);
                                                setSelectedPreset("custom");
                                                setIsDatePopoverOpen(false);
                                            }
                                        }}
                                    />
                                </div>
                            </div>
                        )}
                    </div>
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
                        trend=""
                        trendType="neutral"
                        svg="/icons/tasksSum.svg"
                        footer={selectedPreset === "today" ? "За сегодня" : selectedPreset === "week" ? "За 7 дней" : "За выбранный период"}
                        loading={isSummaryLoading}
                    />
                </div>

                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Выполнено"
                        num={completedTickets}
                        trend={`${completedPercent}%`}
                        trendType="positive"
                        svg="/icons/comletedTasks.svg"
                        footer={`${completedPercent}% выполнено от общего числа`}
                        loading={isSummaryLoading}
                    />
                </div>

                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Под угрозой SLA"
                        num={atRiskCount}
                        trend={avgDelay > 0 ? `+${avgDelay}м` : "В норме"}
                        trendType={atRiskCount > 0 ? "negative" : "positive"}
                        svg="/icons/expiredTasks.svg"
                        footer={`${atRiskCount} заявок с угрозой задержки`}
                        loading={isStatsLoading}
                    />
                </div>

                <div className={styles.kpiCol}>
                    <SmallStatsCard
                        header="Ср. км / техник"
                        num={`${avgKmPerWorker}`}
                        trend="км/день"
                        trendType="neutral"
                        svg="/icons/person.svg"
                        footer="Средний пробег по маршрутам"
                        loading={isStatsLoading}
                    />
                </div>

                {/* 2. Средний ряд: Загрузка бригад (7 колонок) */}
                <div className={styles.workloadCol}>
                    <BrigadesWorkloadCard
                        date={workloadDate}
                        date_from={workloadDateFrom}
                        date_to={workloadDateTo}
                        periodLabel={getFilterLabel()}
                        onOpenJournal={() => setIsJournalModalOpen(true)}
                        onUploadClick={() => setManualOpenModal(true)}
                    />
                </div>

                {/* 3. Средний ряд: Последние события (5 колонок) */}
                <div className={styles.activityCol}>
                    <RecentActivityCard
                        onOpenJournal={() => setIsEventsModalOpen(true)}
                        onUploadClick={() => setManualOpenModal(true)}
                    />
                </div>

                {/* 4. Нижний блок: Выгрузка отчётов (12 колонок) */}
                <div className={styles.reportsCol}>
                    <ReportsExportSection />
                </div>
            </div>

            {/* Модальное окно загрузки данных при пустой БД или клике на кнопку */}
            <EmptyDataModal
                isOpen={isUploadModalOpen}
                onClose={handleCloseModal}
            />

            {/* Модальное окно журнала бригад */}
            <BrigadesJournalModal
                isOpen={isJournalModalOpen}
                onClose={() => setIsJournalModalOpen(false)}
                date={workloadDate}
                date_from={workloadDateFrom}
                date_to={workloadDateTo}
                periodLabel={getFilterLabel()}
                initialSearch={dashboardSearch}
            />

            {/* Модальное окно журнала событий */}
            <EventsJournalModal
                isOpen={isEventsModalOpen}
                onClose={() => setIsEventsModalOpen(false)}
            />
        </div>
    );
};

export default Dashboard;