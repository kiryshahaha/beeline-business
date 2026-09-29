// frontend/src/app/worker/page.jsx
"use client";

import React, { useState } from "react";
import { useMyDay } from "@/hooks/worker/useMyDay";
import { useAvailableDates } from "@/hooks/useAvailableDates";
import {
  getTodayMsk,
  getTomorrowMsk,
  formatMskTime,
  formatMskDayMonth,
  formatMskDateFull,
} from "@/lib/worker/time";
import TicketCard from "@/components/worker/TicketCard";
import styles from "./page.module.css";

export default function WorkerHomePage() {
  const todayMsk = getTodayMsk();
  const tomorrowMsk = getTomorrowMsk();
  const [selectedDate, setSelectedDate] = useState(todayMsk);
  const { hasToday, closestDate } = useAvailableDates(todayMsk);

  React.useEffect(() => {
    if (!hasToday && closestDate && closestDate !== todayMsk) {
      queueMicrotask(() => {
        setSelectedDate(closestDate);
      });
    }
  }, [hasToday, closestDate, todayMsk]);

  const {
    data: dayData,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
  } = useMyDay(selectedDate);

  const isToday = selectedDate === todayMsk;

  if (isLoading) {
    return (
      <div className={styles.container}>
        <div className={styles.skeletonDateBar} />
        <div className={styles.layoutGrid}>
          <div className={styles.skeletonCard} />
          <div className={styles.skeletonCard} />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBox}>
          <div className={styles.errorIcon}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>
          <div className={styles.errorTitle}>Не удалось загрузить план дня</div>
          <div className={styles.errorMsg}>
            {error?.message || "Ошибка соединения с сервером"}
          </div>
          <button type="button" className={styles.retryBtn} onClick={() => refetch()}>
            Повторить попытку
          </button>
        </div>
      </div>
    );
  }

  const {
    worker,
    shift,
    day_state,
    plan,
    summary,
    current_ticket_id,
    next_ticket_id,
    tickets = [],
    removed_tickets = [],
  } = dayData || {};

  const currentTicket = isToday ? tickets.find((t) => t.id === current_ticket_id) : null;
  const nextTicket = isToday ? tickets.find((t) => t.id === next_ticket_id) : null;

  return (
    <div className={styles.container}>
      {/* Top Bar: Switcher + Profile snippet + Summary */}
      <div className={styles.topControlCard}>
        <div className={styles.topControlLeft}>
          <div className={styles.dateToggle}>
            <button
              type="button"
              className={`${styles.dateBtn} ${isToday ? styles.dateBtnActive : ""}`}
              onClick={() => setSelectedDate(todayMsk)}
            >
              <span>Сегодня</span>
              <span className={styles.dateSub}>{formatMskDayMonth(todayMsk)}</span>
            </button>
            <button
              type="button"
              className={`${styles.dateBtn} ${!isToday ? styles.dateBtnActive : ""}`}
              onClick={() => setSelectedDate(tomorrowMsk)}
            >
              <span>Завтра</span>
              <span className={styles.dateSub}>{formatMskDayMonth(tomorrowMsk)}</span>
            </button>
          </div>

          <div className={styles.workerMetaInfo}>
            <h1 className={styles.workerName}>
              {worker?.name} {worker?.surname}
            </h1>
            <div className={styles.workerMetaTags}>
              {worker?.service_area?.name && (
                <span className={styles.metaBadge}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                  <span>Участок {worker.service_area.name}</span>
                </span>
              )}
              {worker?.brigade?.name && (
                <span className={styles.metaBadge}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                  <span>{worker.brigade.name}</span>
                </span>
              )}
              {isFetching && (
                <span className={styles.refreshBadge}>Обновление...</span>
              )}
            </div>
          </div>
        </div>

        {/* Summary Counters */}
        {summary && (
          <div className={styles.summaryBar}>
            <div className={styles.summaryPill} title="Всего заявок">
              <span className={styles.summaryLabel}>Всего</span>
              <span className={styles.summaryValue}>{summary.total}</span>
            </div>
            <div className={`${styles.summaryPill} ${styles.pillCompleted}`} title="Выполнено">
              <span className={styles.summaryLabel}>Готово</span>
              <span className={styles.summaryValue}>{summary.completed}</span>
            </div>
            {summary.awaiting_confirmation > 0 && (
              <div
                className={`${styles.summaryPill} ${styles.pillReview}`}
                title="Ждут проверки диспетчера"
              >
                <span className={styles.summaryLabel}>Проверка</span>
                <span className={styles.summaryValue}>
                  {summary.awaiting_confirmation}
                </span>
              </div>
            )}
            <div className={`${styles.summaryPill} ${styles.pillRemaining}`} title="Осталось в плане">
              <span className={styles.summaryLabel}>Осталось</span>
              <span className={styles.summaryValue}>{summary.remaining}</span>
            </div>
          </div>
        )}
      </div>

      {/* Main Adaptive Layout: Left Column (Current / Shift) + Right Column (All Tickets) */}
      <div className={styles.layoutGrid}>
        {/* LEFT COLUMN: Shift, Plan, Current task, Next preview */}
        <div className={styles.leftCol}>
          {/* Shift Card */}
          <div className={styles.shiftCard}>
            {shift?.is_working_day ? (
              <div className={styles.shiftRow}>
                <span className={styles.shiftBadge}>Рабочий день</span>
                <span className={styles.shiftTime}>
                  Смена: {formatMskTime(shift.start)} – {formatMskTime(shift.end)}
                </span>
              </div>
            ) : (
              <div className={styles.dayOffBanner}>
                <span className={styles.dayOffIcon}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 8h1a4 4 0 0 1 0 8h-1" />
                    <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z" />
                    <line x1="6" y1="1" x2="6" y2="4" />
                    <line x1="10" y1="1" x2="10" y2="4" />
                    <line x1="14" y1="1" x2="14" y2="4" />
                  </svg>
                </span>
                <span className={styles.dayOffText}>
                  {isToday ? "Сегодня выходной день" : "Завтра выходной день"}
                </span>
              </div>
            )}
          </div>

          {/* Tomorrow Notice when looking at tomorrow */}
          {!isToday && (
            <div className={styles.tomorrowNotice}>
              <div className={styles.tomorrowHeader}>Предварительный маршрут</div>
              <div className={styles.tomorrowDate}>
                {formatMskDateFull(selectedDate)}
              </div>
              <div className={styles.tomorrowSub}>
                План сформирован на следующий день. Выполнение и действия по заявкам будут доступны в начале смены.
              </div>
            </div>
          )}

          {/* Unavailable Banner (Only shown today) */}
          {isToday && day_state && !day_state.available && (
            <div className={styles.unavailableBanner}>
              <div className={styles.unavailIcon}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <div className={styles.unavailContent}>
                <div className={styles.unavailTitle}>
                  Вы отмечены недоступным
                  {day_state.unavailable_until &&
                    ` до ${formatMskTime(day_state.unavailable_until)}`}
                </div>
                {day_state.reason && (
                  <div className={styles.unavailReason}>{day_state.reason}</div>
                )}
              </div>
            </div>
          )}

          {/* Plan Status Note */}
          <div className={styles.planStatus}>
            {plan ? (
              <span>
                План обновлён в <strong>{formatMskTime(plan.effective_at)}</strong> (ревизия {plan.revision})
              </span>
            ) : (
              <span className={styles.planPending}>План на этот день ещё не опубликован</span>
            )}
          </div>

          {/* CURRENT TICKET (Today only) */}
          {isToday && currentTicket && (
            <div className={styles.currentSection}>
              <div className={styles.sectionHeaderTitle}>Текущая задача</div>
              <TicketCard
                ticket={currentTicket}
                variant="current"
                onActionComplete={() => refetch()}
              />
            </div>
          )}

          {/* NEXT TICKET PREVIEW (Today only) */}
          {isToday && nextTicket && (
            <div className={styles.nextSection}>
              <div className={styles.sectionHeaderTitle}>Следующая задача</div>
              <TicketCard
                ticket={nextTicket}
                variant="next"
                onActionComplete={() => refetch()}
              />
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Full Route Tickets List + Removed */}
        <div className={styles.rightCol}>
          {/* ALL TICKETS LIST */}
          {tickets.length > 0 && (
            <div className={styles.ticketsSection}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  {isToday ? "Маршрут дня" : "Маршрут на завтра"} ({tickets.length})
                </h2>
                {!plan && (
                  <span className={styles.planWarningNote}>
                    Порядок может измениться
                  </span>
                )}
              </div>
              <div className={styles.ticketList}>
                {tickets.map((t) => (
                  <TicketCard
                    key={t.id}
                    ticket={t}
                    variant={isToday && t.id === current_ticket_id ? "current" : "standard"}
                    onActionComplete={() => refetch()}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Empty Tickets State */}
          {shift?.is_working_day && tickets.length === 0 && (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
                  <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
                  <path d="M9 12h6" />
                  <path d="M9 16h6" />
                </svg>
              </div>
              <div className={styles.emptyTitle}>
                {isToday ? "На сегодня заявок пока нет" : "На завтра заявок пока нет"}
              </div>
              <div className={styles.emptySub}>
                Ожидайте публикации плана или назначения от диспетчера
              </div>
            </div>
          )}

          {!shift?.is_working_day && tickets.length === 0 && (
            <div className={styles.emptyDayNotice}>
              Отдыхайте! На этот день заявок нет.
            </div>
          )}

          {/* REMOVED TICKETS (Today only) */}
          {isToday && removed_tickets.length > 0 && (
            <div className={styles.removedSection}>
              <h3 className={styles.removedHeader}>Сняты с вас сегодня</h3>
              <div className={styles.removedList}>
                {removed_tickets.map((r, idx) => (
                  <div key={idx} className={styles.removedItem}>
                    <div className={styles.removedTitle}>
                      Заявка №{r.ticket_id}: {r.title}
                    </div>
                    <div className={styles.removedReason}>
                      Причина: {r.reason_text || "причина не указана"}
                    </div>
                    <div className={styles.removedTime}>
                      {formatMskTime(r.at)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
