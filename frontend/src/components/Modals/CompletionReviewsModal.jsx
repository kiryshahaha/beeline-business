"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
import styles from "./CompletionReviewsModal.module.css";

function formatMsk(isoString) {
  if (!isoString) return "—";
  try {
    return new Date(isoString).toLocaleString("ru-RU", {
      timeZone: "Europe/Moscow",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

function generateIdempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `rev-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

export default function CompletionReviewsModal({ isOpen, onClose }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("pending");
  const [processingId, setProcessingId] = useState(null);
  const [actionError, setActionError] = useState(null);

  const { data: reviews = [], isLoading, refetch } = useQuery({
    queryKey: ["completionReviews", activeTab],
    queryFn: async () => {
      const res = await apiFetch(`/tickets/completion-reviews?state=${activeTab}`);
      if (!res.ok) {
        throw new Error("Не удалось загрузить заявки на проверку");
      }
      return await res.json();
    },
    enabled: isOpen,
    staleTime: 10000,
  });

  if (!isOpen) return null;

  const handleDecision = async (review, isReject) => {
    setActionError(null);
    let rejectReason = null;
    if (isReject) {
      rejectReason = window.prompt("Укажите причину возврата заявки в работу (обязательно):");
      if (!rejectReason || !rejectReason.trim()) {
        return;
      }
    }

    setProcessingId(review.review_id);
    try {
      // 1. Получаем текущую ревизию заявки
      const ticketRes = await apiFetch(`/tickets/${review.ticket.id}`);
      if (!ticketRes.ok) {
        throw new Error("Не удалось получить актуальные данные заявки");
      }
      const ticketData = await ticketRes.json();
      const expectedRevision = ticketData.revision || 1;

      // 2. Отправляем подтверждение или отклонение
      const endpoint = isReject
        ? `/tickets/${review.ticket.id}/completion/reject`
        : `/tickets/${review.ticket.id}/completion/confirm`;

      const idempotencyKey = generateIdempotencyKey();

      const body = {
        expected_revision: expectedRevision,
        reason: isReject ? rejectReason.trim() : undefined,
        comment: isReject ? "Возвращено диспетчером" : "Подтверждено диспетчером",
      };

      const res = await apiFetch(endpoint, {
        method: "POST",
        headers: {
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        let msg = "Ошибка обработки запроса";
        if (typeof err.detail === "string") msg = err.detail;
        else if (err.detail?.message) msg = err.detail.message;
        else if (err.message) msg = err.message;
        throw new Error(msg);
      }

      await refetch();
      queryClient.invalidateQueries({ queryKey: ["completionReviews"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["fastStats"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
      queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
    } catch (err) {
      setActionError(err.message || "Ошибка при принятии решения");
    } finally {
      setProcessingId(null);
    }
  };

  const pendingCount = activeTab === "pending" ? reviews.length : 0;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <h2 className={styles.title}>Подтверждение выполнения заявок</h2>
            {pendingCount > 0 && <span className={styles.badge}>{pendingCount}</span>}
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose}>
            ✕
          </button>
        </div>

        <div className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "pending" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("pending")}
          >
            Ожидают проверки
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "confirmed" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("confirmed")}
          >
            Подтвержденные
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "rejected" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("rejected")}
          >
            Отклоненные
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "all" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("all")}
          >
            Все
          </button>
        </div>

        <div className={styles.body}>
          {actionError && <div className={styles.errorBanner}>{actionError}</div>}

          {isLoading && (
            <div className={styles.emptyState}>Загрузка списка заявок на проверку...</div>
          )}

          {!isLoading && reviews.length === 0 && (
            <div className={styles.emptyState}>
              {activeTab === "pending"
                ? "Нет заявок, ожидающих подтверждения завершения"
                : "В этой категории нет записей"}
            </div>
          )}

          {!isLoading &&
            reviews.map((r) => (
              <div key={r.review_id} className={styles.reviewCard}>
                <div className={styles.cardHeader}>
                  <div>
                    <div className={styles.ticketTitle}>
                      Заявка #{r.ticket?.id}: {r.ticket?.title}
                    </div>
                    <div className={styles.ticketAddress}>{r.ticket?.address}</div>
                  </div>
                  <span className={`${styles.stateTag} ${styles[`state_${r.state}`]}`}>
                    {r.state === "pending"
                      ? "Ожидает проверки"
                      : r.state === "confirmed"
                      ? "Подтверждено"
                      : "Отклонено"}
                  </span>
                </div>

                <div className={styles.cardMeta}>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Исполнитель:</span>
                    <span>
                      {r.worker?.surname} {r.worker?.name} (#{r.worker?.id})
                    </span>
                  </div>
                  <div className={styles.metaItem}>
                    <span className={styles.metaLabel}>Время завершения:</span>
                    <span>{formatMsk(r.requested_at)}</span>
                  </div>
                  {r.actual_duration_minutes != null && (
                    <div className={styles.metaItem}>
                      <span className={styles.metaLabel}>Фактическая длительность:</span>
                      <span>{r.actual_duration_minutes} мин</span>
                    </div>
                  )}
                </div>

                {r.note && (
                  <div className={styles.workerNote}>
                    <strong>Отчет инженера:</strong> «{r.note}»
                  </div>
                )}

                {r.state === "pending" && (
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className={styles.rejectBtn}
                      onClick={() => handleDecision(r, true)}
                      disabled={processingId === r.review_id}
                    >
                      {processingId === r.review_id ? "Обработка..." : "Вернуть на доработку"}
                    </button>
                    <button
                      type="button"
                      className={styles.confirmBtn}
                      onClick={() => handleDecision(r, false)}
                      disabled={processingId === r.review_id}
                    >
                      {processingId === r.review_id ? "Подтверждение..." : "Принять завершение"}
                    </button>
                  </div>
                )}
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
