// frontend/src/components/worker/DelayModal.jsx
"use client";

import React, { useState } from "react";
import { getFutureTimeIso, formatMskTime } from "@/lib/worker/time";
import styles from "./ActionModal.module.css";

const QUICK_DELAYS = [
  { label: "+15 мин", minutes: 15 },
  { label: "+30 мин", minutes: 30 },
  { label: "+60 мин", minutes: 60 },
];

export default function DelayModal({ isOpen, onClose, ticket, onConfirm, isLoading }) {
  const [selectedMinutes, setSelectedMinutes] = useState(15);
  const [customIso, setCustomIso] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  if (!isOpen || !ticket) return null;

  const handleClose = () => {
    setSelectedMinutes(15);
    setCustomIso("");
    setReason("");
    setError("");
    onClose();
  };

  const handleSelectQuick = (minutes) => {
    setSelectedMinutes(minutes);
    setCustomIso(getFutureTimeIso(minutes));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Укажите причину задержки (обязательно)");
      return;
    }

    const targetIso = customIso || getFutureTimeIso(selectedMinutes);
    if (new Date(targetIso).getTime() <= Date.now()) {
      setError("Время должно быть в будущем");
      return;
    }

    const body = {
      expected_revision: ticket.revision,
      reason: reason.trim(),
      expected_available_at: targetIso,
    };

    onConfirm(body);
  };

  const displayTime = customIso || getFutureTimeIso(selectedMinutes);

  return (
    <div className={styles.overlay} onClick={handleClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <span className={styles.badgeWarning}>Сообщить о задержке</span>
            <h3 className={styles.title}>Заявка №{ticket.id}</h3>
          </div>
          <button type="button" className={styles.closeBtn} onClick={handleClose}>×</button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {error && <div className={styles.errorBox}>{error}</div>}

          <div className={styles.field}>
            <label className={styles.label}>Добавочное время</label>
            <div className={styles.quickButtons}>
              {QUICK_DELAYS.map((q) => (
                <button
                  key={q.minutes}
                  type="button"
                  className={`${styles.quickBtn} ${selectedMinutes === q.minutes ? styles.quickBtnActive : ""}`}
                  onClick={() => handleSelectQuick(q.minutes)}
                >
                  {q.label}
                </button>
              ))}
            </div>
            <div className={styles.subtext}>
              Освобожусь примерно в: <strong>{formatMskTime(displayTime)}</strong>
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="delay-reason">
              Причина задержки <span className={styles.req}>*</span>
            </label>
            <textarea
              id="delay-reason"
              className={styles.textarea}
              placeholder="Пробка, сложные монтажные условия, клиент задерживается..."
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                if (error) setError("");
              }}
              rows={2}
              maxLength={2000}
              autoFocus
            />
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.cancelBtn}
              onClick={handleClose}
              disabled={isLoading}
            >
              Отмена
            </button>
            <button
              type="submit"
              className={styles.submitBtnWarning}
              disabled={isLoading || !reason.trim()}
            >
              {isLoading ? "Отправка..." : "Отправить задержку"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
