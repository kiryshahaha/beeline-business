"use client";

import React, { useState, useEffect } from "react";
import styles from "./EventsJournalModal.module.css";
import { useRecentActivity } from "@/hooks/useRecentActivity";

function renderModalEventIcon(type, color) {
  const stroke = color;
  const bg = `${color}22`;

  return (
    <div className={styles.iconCircle} style={{ backgroundColor: bg, color: stroke }}>
      {type === "check" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <polyline points="9 12 11.5 14.5 15.5 9.5"></polyline>
        </svg>
      )}
      {type === "clock" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <polyline points="12 6 12 12 16 14"></polyline>
        </svg>
      )}
      {type === "user" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
      )}
      {type === "alert" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
      )}
      {type === "comment" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      )}
      {type === "plus" && (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="16"></line>
          <line x1="8" y1="12" x2="16" y2="12"></line>
        </svg>
      )}
    </div>
  );
}

export default function EventsJournalModal({ isOpen, onClose }) {
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all"); // 'all' | 'new' | 'comment' | 'status'

  // Получаем расширенную ленту до 50 событий
  const { events, isLoading } = useRecentActivity({ limit: 50 });

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

  const filteredEvents = (events || []).filter((e) => {
    const matchesSearch =
      e.title.toLowerCase().includes(search.toLowerCase()) ||
      (e.badgeText && e.badgeText.toLowerCase().includes(search.toLowerCase()));

    if (!matchesSearch) return false;

    if (filterType === "new") return e.iconType === "plus";
    if (filterType === "comment") return e.iconType === "comment";
    if (filterType === "status") return e.iconType === "check" || e.iconType === "clock" || e.iconType === "alert";

    return true;
  });

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Хедер */}
        <div className={styles.header}>
          <div className={styles.titleBlock}>
            <div className={styles.titleRow}>
              <h2 className={styles.title}>Журнал операционных событий</h2>
              <span className={styles.badge}>Live Feed</span>
            </div>
            <p className={styles.subtitle}>
              История статусов заявок, назначений, комментариев и системных действий
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

        {/* Фильтры и строка поиска */}
        <div className={styles.filterBar}>
          <div className={styles.searchBox}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8E8E93" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="Поиск по событиям, заявкам, авторам..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className={styles.typeFilters}>
            <button
              type="button"
              className={`${styles.typeFilterBtn} ${filterType === "all" ? styles.typeFilterBtnActive : ""}`}
              onClick={() => setFilterType("all")}
            >
              Все
            </button>
            <button
              type="button"
              className={`${styles.typeFilterBtn} ${filterType === "new" ? styles.typeFilterBtnActive : ""}`}
              onClick={() => setFilterType("new")}
            >
              Новые
            </button>
            <button
              type="button"
              className={`${styles.typeFilterBtn} ${filterType === "comment" ? styles.typeFilterBtnActive : ""}`}
              onClick={() => setFilterType("comment")}
            >
              Комментарии
            </button>
            <button
              type="button"
              className={`${styles.typeFilterBtn} ${filterType === "status" ? styles.typeFilterBtnActive : ""}`}
              onClick={() => setFilterType("status")}
            >
              Статусы
            </button>
          </div>
        </div>

        {/* Список событий */}
        <div className={styles.content}>
          {isLoading ? (
            <div style={{ padding: 24, textAlign: "center", color: "#8E8E93" }}>
              Загрузка журнала событий...
            </div>
          ) : filteredEvents.length > 0 ? (
            filteredEvents.map((event) => (
              <div key={event.id} className={styles.eventRow}>
                {renderModalEventIcon(event.iconType, event.badgeColor)}

                <div className={styles.eventMain}>
                  <span className={styles.eventTitle}>{event.title}</span>
                  <div className={styles.eventMeta}>
                    <span
                      className={styles.eventBadge}
                      style={{
                        backgroundColor: `${event.badgeColor}22`,
                        color: event.badgeColor,
                      }}
                    >
                      {event.badgeText}
                    </span>
                    <span>Операционный журнал</span>
                  </div>
                </div>

                <span className={styles.eventTime}>{event.formattedTime}</span>
              </div>
            ))
          ) : (
            <div style={{ padding: 40, textAlign: "center", color: "#8E8E93" }}>
              События не найдены по заданным критериям
            </div>
          )}
        </div>

        {/* Футер */}
        <div className={styles.footer}>
          <span className={styles.footerStats}>
            Отображено событий: <strong style={{ color: "#FFFFFF" }}>{filteredEvents.length}</strong>
          </span>
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
