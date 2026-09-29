"use client";

import React, { useState, useEffect } from "react";
import styles from "./BrigadesJournalModal.module.css";

const MOCK_JOURNAL_DATA = [
  {
    id: 1,
    name: "Бригада 42-1",
    foreman: "Иванов Алексей",
    workersCount: 2,
    activeTasks: 11,
    completedToday: 5,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "7.2 ч",
    travelHours: "1.4 ч",
    efficiency: "94%",
  },
  {
    id: 2,
    name: "Бригада 42-2",
    foreman: "Смирнов Дмитрий",
    workersCount: 3,
    activeTasks: 14,
    completedToday: 8,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "8.1 ч",
    travelHours: "1.9 ч",
    efficiency: "98%",
  },
  {
    id: 3,
    name: "Бригада 42-3",
    foreman: "Кузнецов Михаил",
    workersCount: 2,
    activeTasks: 13,
    completedToday: 6,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "7.8 ч",
    travelHours: "1.5 ч",
    efficiency: "91%",
  },
  {
    id: 4,
    name: "Бригада 42-4",
    foreman: "Попов Сергей",
    workersCount: 2,
    activeTasks: 14,
    completedToday: 7,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "7.9 ч",
    travelHours: "1.6 ч",
    efficiency: "95%",
  },
  {
    id: 5,
    name: "Бригада 42-5",
    foreman: "Васильев Роман",
    workersCount: 3,
    activeTasks: 15,
    completedToday: 9,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "8.4 ч",
    travelHours: "1.8 ч",
    efficiency: "96%",
  },
  {
    id: 6,
    name: "Бригада 42-6",
    foreman: "Новиков Артем",
    workersCount: 2,
    activeTasks: 13,
    completedToday: 6,
    status: "overloaded",
    statusLabel: "Перегружена",
    statusColor: "#FF3B30",
    serviceHours: "7.6 ч",
    travelHours: "1.7 ч",
    efficiency: "89%",
  },
];

export default function BrigadesJournalModal({ isOpen, onClose }) {
  const [search, setSearch] = useState("");

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

  const filteredBrigades = MOCK_JOURNAL_DATA.filter((b) =>
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
              <span className={styles.badge}>Live</span>
            </div>
            <p className={styles.subtitle}>
              Оперативная сводка по бригадам, сменам и активным назначениям
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
            Всего активных бригад: <strong style={{ color: "#FFFFFF" }}>{filteredBrigades.length}</strong>
          </div>
        </div>

        {/* Контент: таблица журнала */}
        <div className={styles.content}>
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
                    <div style={{ fontSize: 11, color: "#8E8E93" }}>{b.workersCount} монтажника</div>
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
        </div>

        {/* Футер */}
        <div className={styles.footer}>
          <button
            type="button"
            className={styles.exportBtn}
            onClick={() => alert("Выгрузка журнала сформирована")}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>Экспорт в Excel</span>
          </button>
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
