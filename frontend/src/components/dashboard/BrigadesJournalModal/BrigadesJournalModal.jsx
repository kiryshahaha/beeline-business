"use client";

import React, { useState, useEffect } from "react";
import styles from "./BrigadesJournalModal.module.css";
import { useBrigadesWorkload } from "@/hooks/useBrigadesWorkload";
import { useBrigades } from "@/hooks/useBrigades";

export default function BrigadesJournalModal({
  isOpen,
  onClose,
  date,
  date_from,
  date_to,
  periodLabel,
  initialSearch = "",
}) {
  const [search, setSearch] = useState(initialSearch || "");
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);

  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setSearch(initialSearch || "");
    }
  }

  const { brigades: workloadList = [], isLoading } = useBrigadesWorkload({
    date,
    date_from,
    date_to,
  });
  const { brigades = [] } = useBrigades();

  const brigadeForemanMap = React.useMemo(() => {
    const map = {};
    brigades.forEach((b) => {
      map[b.id] = b.foreman_name || "Бригадир";
    });
    return map;
  }, [brigades]);

  useEffect(() => {
    if (isOpen) {
      const originalBodyOverflow = document.body.style.overflow;
      const originalHtmlOverflow = document.documentElement.style.overflow;
      document.body.style.overflow = "hidden";
      document.documentElement.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = originalBodyOverflow;
        document.documentElement.style.overflow = originalHtmlOverflow;
      };
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const isPeriod = Boolean(date_from && date_to) || !date;

  const tableData = workloadList.map((item) => {
    const serviceHours = `${((item.serviceMinutes || 0) / 60).toFixed(1)} ч`;
    const travelHours = `${((item.travelMinutes || 0) / 60).toFixed(1)} ч`;
    return {
      id: item.id,
      name: item.name,
      foreman: brigadeForemanMap[item.id] || "Бригадир назначен",
      workersCount: item.workers || 0,
      activeTasks: item.activeTasks || 0,
      completedToday: item.completedToday || 0,
      status: item.status,
      statusLabel: item.statusLabel,
      statusColor: item.color,
      serviceHours,
      travelHours,
    };
  });

  const filteredBrigades = tableData.filter((b) =>
    b.name.toLowerCase().includes(search.toLowerCase()) ||
    b.foreman.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Хедер */}
        <div className={styles.header}>
          <div className={styles.titleBlock}>
            <div className={styles.titleRow}>
              <h2 className={styles.title}>Журнал смен и загрузки бригад</h2>
              {periodLabel && (
                <span
                  style={{
                    background: "rgba(255, 200, 0, 0.15)",
                    color: "var(--beeline, #ffc800)",
                    fontSize: "11px",
                    fontWeight: 700,
                    padding: "2px 8px",
                    borderRadius: "6px",
                    border: "1px solid rgba(255, 200, 0, 0.25)",
                  }}
                >
                  {periodLabel}
                </span>
              )}
              <span className={styles.badge}>Live</span>
            </div>
            <p className={styles.subtitle}>
              {isPeriod
                ? `Среднесуточная сводка по бригадам и сменным назначениям за выбранный период`
                : "Оперативная сводка по бригадам, сменам и активным назначениям"}
            </p>
          </div>

          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Закрыть"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        {/* Фильтры и быстрый поиск */}
        <div className={styles.filterBar}>
          <div className={styles.searchBox}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8E8E93" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="Поиск по бригаде или бригадиру..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className={styles.summaryPill}>
            Всего бригад в плане: <strong style={{ color: "#FFFFFF" }}>{filteredBrigades.length}</strong>
          </div>
        </div>

        {/* Контент: таблица журнала */}
        <div className={styles.content}>
          {isLoading && (
            <div style={{ padding: "40px 20px", textAlign: "center", color: "#8E8E93" }}>
              Загрузка журнала загрузки бригад...
            </div>
          )}

          {!isLoading && filteredBrigades.length === 0 && (
            <div style={{ padding: "40px 20px", textAlign: "center", color: "#8E8E93" }}>
              Нет данных о бригадах по текущему фильтру
            </div>
          )}

          {!isLoading && filteredBrigades.length > 0 && (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.th}>Бригада</th>
                  <th className={styles.th}>Бригадир / Состав</th>
                  <th className={styles.th}>В работе</th>
                  <th className={styles.th}>Выполнено</th>
                  <th className={styles.th}>Время в работе</th>
                  <th className={styles.th}>Статус</th>
                </tr>
              </thead>
              <tbody>
                {filteredBrigades.map((b) => (
                  <tr key={b.id} className={styles.tr}>
                    <td className={`${styles.td} ${styles.brigadeNameCell}`}>{b.name}</td>
                    <td className={styles.td}>
                      <div>{b.foreman}</div>
                      <div style={{ fontSize: 11, color: "#8E8E93" }}>{b.workersCount} специалистов</div>
                    </td>
                    <td className={styles.td}>
                      <span style={{ fontWeight: 700, color: "#FFC800" }}>{b.activeTasks}</span> задач
                    </td>
                    <td className={styles.td}>
                      <span style={{ color: "#34C759", fontWeight: 600 }}>{b.completedToday}</span> задач
                    </td>
                    <td className={styles.td}>
                      <div>{b.serviceHours}</div>
                      <div style={{ fontSize: 11, color: "#8E8E93" }}>+ {b.travelHours} в пути</div>
                    </td>
                    <td className={styles.td}>
                      <span
                        className={styles.statusBadge}
                        style={{
                          backgroundColor: `${b.statusColor}22`,
                          color: b.statusColor,
                        }}
                      >
                        <span
                          className={styles.statusDot}
                          style={{ backgroundColor: b.statusColor }}
                        />
                        {b.statusLabel}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Футер */}
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.doneBtn}
            onClick={onClose}
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  );
}
