// frontend/src/components/worker/TicketCard.jsx
"use client";

import React from "react";
import Link from "next/link";
import { formatMskTime } from "@/lib/worker/time";
import { getTicketStateBadge } from "@/lib/worker/labels";
import ActionBar from "./ActionBar";
import styles from "./TicketCard.module.css";

export default function TicketCard({
  ticket,
  variant = "standard", // "current" | "next" | "standard"
  onActionComplete,
}) {
  if (!ticket) return null;

  const isCurrent = variant === "current";
  const isNext = variant === "next";
  const isEmergency = ticket.category === "emergency" || ticket.work_type === "emergency";
  const stateBadge = getTicketStateBadge(ticket);

  const arrivalText = ticket.planned_arrival_at
    ? `Прибытие ~${formatMskTime(ticket.planned_arrival_at)}`
    : null;

  const windowText =
    ticket.visit_window_start && ticket.visit_window_end
      ? `Окно ${formatMskTime(ticket.visit_window_start)}–${formatMskTime(ticket.visit_window_end)}`
      : null;

  const address =
    ticket.location?.address || ticket.address || "Адрес не указан";

  const yandexNavUrl =
    ticket.location?.lat && ticket.location?.lon
      ? `https://yandex.ru/maps/?rtext=~${ticket.location.lat},${ticket.location.lon}&rtt=auto`
      : null;

  if (isNext) {
    return (
      <Link href={`/worker/tickets/${ticket.id}`} className={styles.nextCard}>
        <div className={styles.nextHeader}>
          <div className={styles.nextLabel}>СЛЕДУЮЩАЯ ЗАЯВКА</div>
          {ticket.sequence && (
            <span className={styles.seqTag}>№{ticket.sequence}</span>
          )}
        </div>
        <div className={styles.nextTitle}>{ticket.title}</div>
        <div className={styles.nextAddress}>{address}</div>
        <div className={styles.nextMeta}>
          {arrivalText && <span className={styles.timeBadge}>{arrivalText}</span>}
          {windowText && <span className={styles.windowBadge}>{windowText}</span>}
        </div>
      </Link>
    );
  }

  return (
    <div className={`${styles.card} ${isCurrent ? styles.currentCard : ""}`}>
      {isCurrent && (
        <div className={styles.currentHeaderBanner}>
          <span className={styles.liveIndicator}>● ТЕКУЩАЯ ЗАЯВКА</span>
          {ticket.sequence && <span className={styles.seqTag}>№{ticket.sequence}</span>}
        </div>
      )}

      <div className={styles.contentWrap}>
        <div className={styles.topRow}>
          <div className={styles.seqAndState}>
            {!isCurrent && ticket.sequence && (
              <span className={styles.seqBadge}>№{ticket.sequence}</span>
            )}
            <span
              className={styles.stateBadge}
              style={{
                background: stateBadge.color.bg,
                color: stateBadge.color.text,
                borderColor: stateBadge.color.border,
              }}
            >
              {stateBadge.label}
            </span>
            {isEmergency && <span className={styles.emergencyTag}>Авария</span>}
          </div>

          <div className={styles.topActions}>
            <Link
              href={`/worker/map?ticket_id=${ticket.id}`}
              className={styles.mapActionLink}
              title="Открыть на встроенной карте"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
                <line x1="8" y1="2" x2="8" y2="18" />
                <line x1="16" y1="6" x2="16" y2="22" />
              </svg>
              <span>Карта</span>
            </Link>

            {yandexNavUrl && (
              <a
                href={yandexNavUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.yandexActionLink}
                title="Открыть в Яндекс.Картах"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
                </svg>
                <span>Яндекс</span>
              </a>
            )}

            <Link href={`/worker/tickets/${ticket.id}`} className={styles.openLink}>
              Подробнее →
            </Link>
          </div>
        </div>

        <Link href={`/worker/tickets/${ticket.id}`} className={styles.mainInfo}>
          <h3 className={styles.ticketTitle}>{ticket.title}</h3>
          <div className={styles.addressRow}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
            <span className={styles.addressText}>{address}</span>
          </div>

          <div className={styles.timesRow}>
            {arrivalText && (
              <span className={styles.timeBadge}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                {arrivalText}
              </span>
            )}
            {windowText && (
              <span className={styles.windowBadge}>
                {windowText}
              </span>
            )}
          </div>

          {ticket.last_change?.reason_text && (
            <div className={styles.lastChangeRow}>
              Изменено: {ticket.last_change.reason_text}
            </div>
          )}

          <div className={styles.bottomMeta}>
            {ticket.required_appliances && ticket.required_appliances.length > 0 && (
              <span className={styles.metaChip} title="Оборудование к заявке">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }}>
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
                  <line x1="12" y1="22.08" x2="12" y2="12" />
                </svg>
                {ticket.required_appliances.length} поз.
              </span>
            )}
            {ticket.comments_count > 0 && (
              <span className={styles.metaChip} title="Комментарии">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }}>
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                {ticket.comments_count}
              </span>
            )}
          </div>
        </Link>

        {isCurrent && (
          <div className={styles.actionBarWrap}>
            <ActionBar ticket={ticket} onActionComplete={onActionComplete} />
          </div>
        )}
      </div>
    </div>
  );
}
