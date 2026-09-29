// frontend/src/components/worker/ActionBar.jsx
"use client";

import React, { useState } from "react";
import { useTicketAction } from "@/hooks/worker/useTicketAction";
import CompleteModal from "./CompleteModal";
import DelayModal from "./DelayModal";
import ProblemModal from "./ProblemModal";
import styles from "./ActionBar.module.css";

export default function ActionBar({ ticket, onActionComplete }) {
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [delayModalOpen, setDelayModalOpen] = useState(false);
  const [problemModalOpen, setProblemModalOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const ticketAction = useTicketAction();

  if (!ticket) return null;

  const state = ticket.state;
  const isPendingReview = state === "completed" && ticket.completion_review?.state === "pending";
  const isTerminal = (state === "completed" && !isPendingReview) || state === "cancelled";

  // Handlers for instant actions
  const handleStartRoute = async () => {
    setErrorMessage(null);
    try {
      await ticketAction.mutateAsync({
        path: `/tickets/${ticket.id}/start-route`,
        body: { expected_revision: ticket.revision },
        ticketId: ticket.id,
      });
      onActionComplete && onActionComplete();
    } catch (err) {
      setErrorMessage(err.message || "Не удалось отметить выезд");
    }
  };

  const handleStartWork = async () => {
    setErrorMessage(null);
    try {
      await ticketAction.mutateAsync({
        path: `/tickets/${ticket.id}/start`,
        body: { expected_revision: ticket.revision },
        ticketId: ticket.id,
      });
      onActionComplete && onActionComplete();
    } catch (err) {
      setErrorMessage(err.message || "Не удалось начать работу");
    }
  };

  // Handlers for modal submissions
  const handleCompleteSubmit = async (body) => {
    setErrorMessage(null);
    try {
      await ticketAction.mutateAsync({
        path: `/tickets/${ticket.id}/complete`,
        body,
        ticketId: ticket.id,
      });
      setCompleteModalOpen(false);
      onActionComplete && onActionComplete();
    } catch (err) {
      setErrorMessage(err.message || "Не удалось завершить заявку");
    }
  };

  const handleDelaySubmit = async (body) => {
    setErrorMessage(null);
    try {
      await ticketAction.mutateAsync({
        path: `/tickets/${ticket.id}/delay`,
        body,
        ticketId: ticket.id,
      });
      setDelayModalOpen(false);
      onActionComplete && onActionComplete();
    } catch (err) {
      setErrorMessage(err.message || "Не удалось отправить задержку");
    }
  };

  const handleProblemSubmit = async (body) => {
    setErrorMessage(null);
    try {
      await ticketAction.mutateAsync({
        path: `/tickets/${ticket.id}/problem`,
        body,
        ticketId: ticket.id,
      });
      setProblemModalOpen(false);
      onActionComplete && onActionComplete();
    } catch (err) {
      setErrorMessage(err.message || "Не удалось отправить отчет о проблеме");
    }
  };

  return (
    <>
      <div className={styles.bar}>
        {errorMessage && (
          <div className={styles.errorAlert}>
            <span>{errorMessage}</span>
            <button
              type="button"
              className={styles.closeAlertBtn}
              onClick={() => setErrorMessage(null)}
              aria-label="Закрыть"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        )}

        {isPendingReview ? (
          <div className={styles.pendingBadge}>
            <span className={styles.badgePulse} />
            <span>Ждёт подтверждения диспетчера</span>
          </div>
        ) : isTerminal ? (
          <div className={styles.terminalBadge}>
            <span>{state === "completed" ? "Заявка выполнена" : "Заявка отменена"}</span>
          </div>
        ) : (
          <div className={styles.actionsContainer}>
            {/* Secondary actions */}
            <div className={styles.secondaryRow}>
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => setDelayModalOpen(true)}
                disabled={ticketAction.isPending}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <span>Задерживаюсь</span>
              </button>
              <button
                type="button"
                className={`${styles.secondaryBtn} ${styles.problemBtn}`}
                onClick={() => setProblemModalOpen(true)}
                disabled={ticketAction.isPending}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                <span>Проблема</span>
              </button>
            </div>

            {/* Primary action */}
            {(state === "assigned" || state === "dispatched") && (
              <button
                type="button"
                className={`${styles.primaryBtn} ${styles.startRouteBtn}`}
                onClick={handleStartRoute}
                disabled={ticketAction.isPending}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="3 11 22 2 13 21 11 13 3 11" />
                </svg>
                <span>{ticketAction.isPending ? "Отправка..." : "Выехал"}</span>
              </button>
            )}

            {state === "en_route" && (
              <button
                type="button"
                className={`${styles.primaryBtn} ${styles.startWorkBtn}`}
                onClick={handleStartWork}
                disabled={ticketAction.isPending}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                <span>{ticketAction.isPending ? "Отправка..." : "Начать работу"}</span>
              </button>
            )}

            {state === "in_progress" && (
              <button
                type="button"
                className={`${styles.primaryBtn} ${styles.completeBtn}`}
                onClick={() => setCompleteModalOpen(true)}
                disabled={ticketAction.isPending}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span>{ticketAction.isPending ? "Отправка..." : "Завершить работу"}</span>
              </button>
            )}
          </div>
        )}
      </div>

      <CompleteModal
        isOpen={completeModalOpen}
        onClose={() => setCompleteModalOpen(false)}
        ticket={ticket}
        onConfirm={handleCompleteSubmit}
        isLoading={ticketAction.isPending}
      />

      <DelayModal
        isOpen={delayModalOpen}
        onClose={() => setDelayModalOpen(false)}
        ticket={ticket}
        onConfirm={handleDelaySubmit}
        isLoading={ticketAction.isPending}
      />

      <ProblemModal
        isOpen={problemModalOpen}
        onClose={() => setProblemModalOpen(false)}
        ticket={ticket}
        onConfirm={handleProblemSubmit}
        isLoading={ticketAction.isPending}
      />
    </>
  );
}
