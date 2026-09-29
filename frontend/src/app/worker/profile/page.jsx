// frontend/src/app/worker/profile/page.jsx
"use client";

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { useMyDay } from "@/hooks/worker/useMyDay";
import {
  fetchCalendarTokenStatus,
  issueCalendarToken,
  revokeCalendarToken,
} from "@/lib/worker/api";
import { formatMskDateTime } from "@/lib/worker/time";
import { TRANSPORT_TYPE_LABELS } from "@/lib/worker/labels";
import styles from "./profile.module.css";

export default function WorkerProfilePage() {
  const { user, logout } = useAuth();
  const queryClient = useQueryClient();
  const { data: dayData } = useMyDay();
  const worker = dayData?.worker || user;

  const [copied, setCopied] = useState(false);
  const [issuedUrl, setIssuedUrl] = useState(null);
  const [calendarError, setCalendarError] = useState(null);

  // Calendar token status query
  const {
    data: calendarStatus,
    refetch: refetchCalStatus,
  } = useQuery({
    queryKey: ["calendarTokenStatus"],
    queryFn: fetchCalendarTokenStatus,
    staleTime: 30000,
  });

  // Issue token mutation
  const issueMutation = useMutation({
    mutationFn: issueCalendarToken,
    onSuccess: (data) => {
      setIssuedUrl(data.url);
      setCalendarError(null);
      refetchCalStatus();
      queryClient.invalidateQueries({ queryKey: ["calendarTokenStatus"] });
    },
    onError: (err) => {
      setCalendarError(err.message || "Не удалось выпустить ссылку");
    },
  });

  // Revoke token mutation
  const revokeMutation = useMutation({
    mutationFn: revokeCalendarToken,
    onSuccess: () => {
      setIssuedUrl(null);
      setCalendarError(null);
      refetchCalStatus();
      queryClient.invalidateQueries({ queryKey: ["calendarTokenStatus"] });
    },
    onError: (err) => {
      setCalendarError(err.message || "Не удалось отозвать ссылку");
    },
  });

  const handleCopy = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // fallback
    }
  };

  const transportLabel =
    TRANSPORT_TYPE_LABELS[worker?.transport_type] ||
    worker?.transport_type ||
    "Не указан";

  return (
    <div className={styles.container}>
      {/* Left Column (Desktop) */}
      <div className={styles.leftCol}>
        {/* Worker Card */}
        <div className={styles.profileCard}>
          <div className={styles.avatarCircle}>
            {worker?.name?.[0] || "И"}
            {worker?.surname?.[0] || "П"}
          </div>
          <div className={styles.profileNames}>
            <h1 className={styles.fullName}>
              {worker?.name} {worker?.surname}
            </h1>
            <span className={styles.roleTag}>
              Сервисный инженер · ID #{worker?.id}
            </span>
          </div>
        </div>

        {/* Skills */}
        {worker?.skills && worker.skills.length > 0 && (
          <div className={styles.skillsSection}>
            <h2 className={styles.sectionTitle}>Квалификация и навыки</h2>
            <div className={styles.skillsList}>
              {worker.skills.map((skill, idx) => (
                <span key={idx} className={styles.skillPill}>
                  {skill}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Logout button */}
        <div className={styles.logoutSection}>
          <button
            type="button"
            className={styles.logoutBtn}
            onClick={logout}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            Выйти из аккаунта
          </button>
        </div>
      </div>

      {/* Right Column (Desktop) */}
      <div className={styles.rightCol}>
        {/* Work Attributes Grid */}
        <div className={styles.infoCard}>
          <h2 className={styles.sectionTitle}>Рабочие параметры</h2>
          <div className={styles.attributesGrid}>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Транспорт</span>
              <span className={styles.infoValue}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }}>
                  <rect x="1" y="3" width="15" height="13" />
                  <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
                  <circle cx="5.5" cy="18.5" r="2.5" />
                  <circle cx="18.5" cy="18.5" r="2.5" />
                </svg>
                {transportLabel}
              </span>
            </div>

            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Участок обслуживания</span>
              <span className={styles.infoValue}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }}>
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                {worker?.service_area?.name || "Основной"}
              </span>
            </div>

            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Бригада</span>
              <span className={styles.infoValue}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }}>
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
                {worker?.brigade?.name || "Не назначена"}
              </span>
            </div>
          </div>

          {worker?.office && (
            <div className={styles.infoItemFull}>
              <span className={styles.infoLabel}>Офис получения склада</span>
              <span className={styles.infoValue}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }}>
                  <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
                  <path d="M9 22v-4h6v4" />
                </svg>
                {worker.office.name}
              </span>
              <span className={styles.infoSub}>{worker.office.address}</span>
            </div>
          )}
        </div>

        {/* Calendar Feed Section */}
        <div className={styles.calendarCard}>
          <div className={styles.calendarHeader}>
            <div className={styles.calendarIcon}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </div>
            <div className={styles.calendarTitleWrap}>
              <h2 className={styles.calendarTitle}>Синхронизация с календарем</h2>
              <span className={styles.calendarSub}>
                Подписка на расписание смен в Apple / Google / Outlook Calendar
              </span>
            </div>
          </div>

          {calendarError && (
            <div className={styles.errorAlert}>{calendarError}</div>
          )}

          <div className={styles.calendarStatusRow}>
            <span className={styles.statusLabel}>Статус подписки:</span>
            {calendarStatus?.active ? (
              <span className={styles.statusActive}>
                ● Активна (создана {formatMskDateTime(calendarStatus.created_at)})
              </span>
            ) : (
              <span className={styles.statusInactive}>○ Не настроена</span>
            )}
          </div>

          {issuedUrl && (
            <div className={styles.issuedBox}>
              <div className={styles.issuedWarning}>
                Ссылка отображается <strong>один раз</strong>. Старая ссылка перестала действовать.
              </div>
              <div className={styles.urlCopyRow}>
                <input
                  className={styles.urlInput}
                  value={issuedUrl}
                  readOnly
                />
                <button
                  type="button"
                  className={styles.copyBtn}
                  onClick={() => handleCopy(issuedUrl)}
                >
                  {copied ? "Скопировано" : "Скопировать"}
                </button>
              </div>
            </div>
          )}

          <div className={styles.calendarActions}>
            <button
              type="button"
              className={styles.issueBtn}
              onClick={() => issueMutation.mutate()}
              disabled={issueMutation.isPending}
            >
              {issueMutation.isPending
                ? "Создание ссылки..."
                : calendarStatus?.active
                ? "Перевыпустить ссылку"
                : "Выпустить ссылку на календарь"}
            </button>

            {calendarStatus?.active && (
              <button
                type="button"
                className={styles.revokeBtn}
                onClick={() => {
                  if (window.confirm("Отозвать ссылку на календарь? Календари перестанут обновляться.")) {
                    revokeMutation.mutate();
                  }
                }}
                disabled={revokeMutation.isPending}
              >
                Отозвать
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
