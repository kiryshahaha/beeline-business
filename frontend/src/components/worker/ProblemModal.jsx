// frontend/src/components/worker/ProblemModal.jsx
"use client";

import React, { useState } from "react";
import { PROBLEM_TYPES } from "@/lib/worker/labels";
import styles from "./ActionModal.module.css";

export default function ProblemModal({ isOpen, onClose, ticket, onConfirm, isLoading }) {
  const [type, setType] = useState("no_access");
  const [text, setText] = useState("");
  const [error, setError] = useState("");

  if (!isOpen || !ticket) return null;

  const handleClose = () => {
    setType("no_access");
    setText("");
    setError("");
    onClose();
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!text.trim()) {
      setError("Опишите возникшую проблему (обязательно)");
      return;
    }

    const body = {
      expected_revision: ticket.revision,
      type,
      text: text.trim(),
    };

    onConfirm(body);
  };

  return (
    <div className={styles.overlay} onClick={handleClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <span className={styles.badgeDanger}>Сообщить о проблеме</span>
            <h3 className={styles.title}>Заявка №{ticket.id}</h3>
          </div>
          <button type="button" className={styles.closeBtn} onClick={handleClose}>×</button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          {error && <div className={styles.errorBox}>{error}</div>}

          <div className={styles.field}>
            <label className={styles.label}>Тип проблемы</label>
            <div className={styles.typeGrid}>
              {PROBLEM_TYPES.map((p) => (
                <button
                  key={p.code}
                  type="button"
                  className={`${styles.typeBtn} ${type === p.code ? styles.typeBtnActive : ""}`}
                  onClick={() => setType(p.code)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="problem-text">
              Подробности ситуации <span className={styles.req}>*</span>
            </label>
            <textarea
              id="problem-text"
              className={styles.textarea}
              placeholder="Что произошло, кто не пускает, какие меры приняты..."
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                if (error) setError("");
              }}
              rows={3}
              maxLength={2000}
              autoFocus
            />
          </div>

          <div className={styles.notice}>
            ℹ️ Статус вашей заявки не изменится. Диспетчер получит экстренное уведомление.
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
              className={styles.submitBtnDanger}
              disabled={isLoading || !text.trim()}
            >
              {isLoading ? "Отправка..." : "Отправить диспетчеру"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
