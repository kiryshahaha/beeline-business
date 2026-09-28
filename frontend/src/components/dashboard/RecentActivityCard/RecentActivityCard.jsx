"use client";

import React from "react";
import styles from "./RecentActivityCard.module.css";
import { useRecentActivity } from "@/hooks/useRecentActivity";

function renderActivityIcon(type, color) {
  const stroke = color;
  const bg = `${color}20`; // 12% прозрачность для круга подложки

  return (
    <div className={styles.iconCircle} style={{ backgroundColor: bg, color: stroke }}>
      {type === "check" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <polyline points="9 12 11.5 14.5 15.5 9.5"></polyline>
        </svg>
      )}
      {type === "clock" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <polyline points="12 6 12 12 16 14"></polyline>
        </svg>
      )}
      {type === "user" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
      )}
      {type === "alert" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
      )}
      {type === "comment" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      )}
      {type === "plus" && (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="16"></line>
          <line x1="8" y1="12" x2="16" y2="12"></line>
        </svg>
      )}
    </div>
  );
}

export default function RecentActivityCard({ onOpenJournal, onUploadClick }) {
  const { events, isLoading } = useRecentActivity({ limit: 6 });

  const hasEvents = events && events.length > 0;

  return (
    <div className={styles.card}>
      {/* Хедер */}
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <h2 className={styles.title}>Последние события</h2>
          <span className={styles.subtitle}>Живая лента операционных изменений</span>
        </div>

        <div className={styles.liveIndicator}>
          <span className={styles.liveDot}></span>
          <span>Авто · 30 сек</span>
        </div>
      </div>

      {/* Список событий */}
      <div className={styles.eventsList}>
        {isLoading ? (
          [1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className={styles.eventItem}>
              <div className={`${styles.skeleton} ${styles.skeletonCircle}`} />
              <div className={styles.contentBlock}>
                <div className={`${styles.skeleton} ${styles.skeletonTitle}`} />
                <div className={`${styles.skeleton} ${styles.skeletonTag}`} style={{ marginTop: 4 }} />
              </div>
              <div className={`${styles.skeleton} ${styles.skeletonTime}`} />
            </div>
          ))
        ) : hasEvents ? (
          events.slice(0, 6).map((event) => (
            <div key={event.id} className={styles.eventItem}>
              {renderActivityIcon(event.iconType, event.badgeColor)}

              <div className={styles.contentBlock}>
                <span className={styles.eventTitle} title={event.title}>
                  {event.title}
                </span>
                <span className={styles.eventTag} style={{ color: event.badgeColor }}>
                  {event.badgeText}
                </span>
              </div>

              <span className={styles.eventTime}>{event.formattedTime}</span>
            </div>
          ))
        ) : (
          <div className={styles.emptyState}>
            <p>Нет операционных событий</p>
            {onUploadClick && (
              <button
                type="button"
                className={styles.emptyActionBtn}
                onClick={onUploadClick}
              >
                Загрузить данные CSV
              </button>
            )}
          </div>
        )}
      </div>

      {/* Футер */}
      <div className={styles.footer}>
        <button
          type="button"
          className={styles.linkBtn}
          onClick={onOpenJournal}
        >
          <span>Открыть журнал событий</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
          </svg>
        </button>
      </div>
    </div>
  );
}
