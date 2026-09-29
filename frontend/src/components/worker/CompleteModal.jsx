// frontend/src/components/worker/CompleteModal.jsx
"use client";

import React, { useState } from "react";
import { calcDurationMinutes } from "@/lib/worker/time";
import styles from "./ActionModal.module.css";

export default function CompleteModal({ isOpen, onClose, ticket, onConfirm, isLoading }) {
  const estMinutes = calcDurationMinutes(ticket?.actual_started_at || ticket?.en_route_started_at);
  const [note, setNote] = useState("");
  const [duration, setDuration] = useState(estMinutes > 0 ? String(estMinutes) : "30");
  const [error, setError] = useState("");

  if (!isOpen || !ticket) return null;

  const handleClose = () => {
    setNote("");
    setError("");
    onClose();
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!note.trim()) {
      setError("Укажите, что было сделано (обязательно)");
      return;
    }

    const dur = parseInt(duration, 10);
    const body = {
      expected_revision: ticket.revision,
      note: note.trim(),
      actual_duration_minutes: !isNaN(dur) && dur >= 0 ? dur : undefined,
    };

    onConfirm(body);
  };

  return (
    <div className={styles.overlay} onClick={handleClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <span className={styles.badgeSuccess}>Завершение работы</span>
            <h3 className={styles.title}>Заявка №{ticket.id}</h3>
          </div>
          <button type="button" className={styles.closeBtn} onClick={handleClose}>×</button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {error && <div className={styles.errorBox}>{error}</div>}

          <div className={styles.field}>
            <label className={styles.label} htmlFor="completion-note">
              Что сделано <span className={styles.req}>*</span>
            </label>
            <textarea
              id="completion-note"
              className={styles.textarea}
              placeholder="Опишите выполненные работы, замененное оборудование, результат..."
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                if (error) setError("");
              }}
              rows={3}
              maxLength={2000}
              autoFocus
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="completion-duration">
              Фактическая длительность (минут)
            </label>
            <input
              id="completion-duration"
              type="number"
              min="0"
              max="1440"
              className={styles.input}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </div>

          <div className={styles.notice}>
            После завершения заявка поступит диспетчеру на подтверждение.
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
              className={styles.submitBtnSuccess}
              disabled={isLoading || !note.trim()}
            >
              {isLoading ? "Отправка..." : "Подтвердить завершение"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
