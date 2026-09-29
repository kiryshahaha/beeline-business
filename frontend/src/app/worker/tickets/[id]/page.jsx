// frontend/src/app/worker/tickets/[id]/page.jsx
"use client";

import React, { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchTicket } from "@/lib/worker/api";
import { useMyDay } from "@/hooks/worker/useMyDay";
import { useTicketChanges } from "@/hooks/worker/useTicketChanges";
import { useTicketComments } from "@/hooks/worker/useTicketComments";
import { formatMskTime, formatMskDateTime } from "@/lib/worker/time";
import { getTicketStateBadge } from "@/lib/worker/labels";
import { useAuth } from "@/providers/AuthProvider";
import ActionBar from "@/components/worker/ActionBar";
import ChangeList from "@/components/worker/ChangeList";
import styles from "./ticket.module.css";

export default function WorkerTicketPage() {
  const params = useParams();
  const router = useRouter();
  const ticketId = parseInt(params.id, 10);
  const { user } = useAuth();

  const [commentText, setCommentText] = useState("");
  const [editingCommentId, setEditingCommentId] = useState(null);
  const [editText, setEditText] = useState("");

  // 1. First check if ticket is cached in today's /me/day
  const { data: myDayData, refetch: refetchMyDay } = useMyDay();
  const cachedTicket = myDayData?.tickets?.find((t) => t.id === ticketId);

  // 2. Direct fetch if not cached or to keep details fresh
  const {
    data: ticketData,
    isLoading: isTicketLoading,
    error: ticketError,
    refetch: refetchTicket,
  } = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => fetchTicket(ticketId),
    enabled: Boolean(ticketId),
    initialData: cachedTicket,
  });

  const ticket = ticketData || cachedTicket;

  // 3. Changes query
  const { data: changesData, refetch: refetchChanges } = useTicketChanges(ticketId);
  const changes = changesData?.changes || [];

  // 4. Comments query and actions
  const {
    comments,
    addComment,
    isAdding,
    updateComment,
    isUpdating,
    refetch: refetchComments,
  } = useTicketComments(ticketId);

  const handleActionComplete = () => {
    refetchTicket();
    refetchMyDay();
    refetchChanges();
    refetchComments();
  };

  const handleAddComment = async (e) => {
    e.preventDefault();
    if (!commentText.trim()) return;
    try {
      await addComment(commentText.trim());
      setCommentText("");
    } catch {
      // error handled by hook
    }
  };

  const handleStartEdit = (comm) => {
    setEditingCommentId(comm.id);
    setEditText(comm.text);
  };

  const handleSaveEdit = async (commId) => {
    if (!editText.trim()) return;
    try {
      await updateComment({ commentId: commId, text: editText.trim() });
      setEditingCommentId(null);
    } catch {
      // error handled by hook
    }
  };

  if (isTicketLoading && !ticket) {
    return (
      <div className={styles.container}>
        <div className={styles.loadingBox}>Загрузка карточки заявки...</div>
      </div>
    );
  }

  if (ticketError && !ticket) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBox}>
          <h3>Заявка не найдена</h3>
          <p>{ticketError.message || "Возможно, заявка была снята или передана другому инженеру"}</p>
          <button type="button" className={styles.backBtn} onClick={() => router.push("/worker")}>
            Вернуться в «Мой день»
          </button>
        </div>
      </div>
    );
  }

  const isEmergency = ticket.category === "emergency" || ticket.work_type === "emergency";
  const stateBadge = getTicketStateBadge(ticket);

  // Address and coordinates for Yandex Navigator
  const address = ticket.location?.address || ticket.address || "Адрес не указан";
  const lat = ticket.location?.latitude ?? ticket.latitude;
  const lon = ticket.location?.longitude ?? ticket.longitude;
  const navUrl =
    lat != null && lon != null
      ? `https://yandex.ru/maps/?rtext=~${lat},${lon}&rtt=auto`
      : null;

  const arrivalText = ticket.planned_arrival_at
    ? formatMskTime(ticket.planned_arrival_at)
    : null;

  const windowText =
    ticket.visit_window_start && ticket.visit_window_end
      ? `${formatMskTime(ticket.visit_window_start)} – ${formatMskTime(ticket.visit_window_end)}`
      : null;

  const appliances = ticket.required_appliances || [];

  return (
    <div className={styles.container}>
      {/* Top Bar with Back Link */}
      <div className={styles.topBar}>
        <button type="button" className={styles.backLink} onClick={() => router.push("/worker")}>
          ← Назад в «Мой день»
        </button>
        <span className={styles.topId}>Заявка №{ticket.id}</span>
      </div>

      {/* Adaptive 2-Column Details Grid on Desktop */}
      <div className={styles.detailsGrid}>
        {/* LEFT COLUMN: Main Info, Actions, Timing, Equipment */}
        <div className={styles.leftCol}>
          {/* Main Card Header */}
          <div className={styles.cardHeader}>
            <div className={styles.badgesRow}>
              {ticket.sequence && <span className={styles.seqBadge}>№{ticket.sequence} в маршруте</span>}
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
              {isEmergency && <span className={styles.emergencyBadge}>Авария</span>}
            </div>

            <h1 className={styles.title}>{ticket.title}</h1>

            <div className={styles.addressBlock}>
              <div className={styles.addressRow}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                <span className={styles.addressText}>{address}</span>
              </div>

              <div className={styles.navRow}>
                <Link
                  href={`/worker/map?ticket_id=${ticket.id}`}
                  className={styles.inAppMapBtn}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
                    <line x1="8" y1="2" x2="8" y2="18" />
                    <line x1="16" y1="6" x2="16" y2="22" />
                  </svg>
                  <span>Показать на карте</span>
                </Link>

                {navUrl && (
                  <a
                    href={navUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.yandexMapsBtn}
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" />
                      <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
                    </svg>
                    <span>Яндекс.Карты</span>
                  </a>
                )}
              </div>
            </div>
          </div>

          {/* Action Bar Prominent */}
          <div className={styles.actionBarContainer}>
            <ActionBar ticket={ticket} onActionComplete={handleActionComplete} />
          </div>

          {/* Visit Times & Duration Grid */}
          <div className={styles.timingCard}>
            <div className={styles.timingItem}>
              <span className={styles.timingLabel}>Окно визита</span>
              <span className={styles.timingValue}>{windowText || "Не указано"}</span>
            </div>
            <div className={styles.timingItem}>
              <span className={styles.timingLabel}>Плановое прибытие</span>
              <span className={styles.timingValue}>
                {arrivalText ? `~${arrivalText}` : "По расписанию"}
              </span>
            </div>
            <div className={styles.timingItem}>
              <span className={styles.timingLabel}>Оценка длительности</span>
              <span className={styles.timingValue}>
                {ticket.estimated_duration_minutes ? `${ticket.estimated_duration_minutes} мин` : "—"}
              </span>
            </div>
            <div className={styles.timingItem}>
              <span className={styles.timingLabel}>Категория</span>
              <span className={styles.timingValue}>{ticket.work_type || ticket.category || "Стандарт"}</span>
            </div>
          </div>

          {/* Equipment Required for this ticket */}
          <div className={styles.sectionBlock}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Оборудование к заявке ({appliances.length})</h2>
            </div>
            {appliances.length === 0 ? (
              <div className={styles.emptyNote}>Специального оборудования не требуется</div>
            ) : (
              <div className={styles.applianceList}>
                {appliances.map((app, index) => (
                  <div key={app.appliance_id || index} className={styles.applianceItem}>
                    <div className={styles.applianceName}>
                      {app.appliance_name || app.name || "Оборудование"}
                    </div>
                    <div className={styles.applianceQty}>
                      {app.quantity} {app.unit || "шт."}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Assistant Banner, Comments, Changes History */}
        <div className={styles.rightCol}>
          {/* Ask Assistant for this Ticket button */}
          <div className={styles.assistantPromo}>
            <Link href={`/worker/chat?ticket_id=${ticket.id}`} className={styles.assistantBtn}>
              <span className={styles.assistantIcon}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2 2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z" />
                  <rect x="4" y="8" width="16" height="12" rx="2" />
                  <circle cx="9" cy="13" r="1" />
                  <circle cx="15" cy="13" r="1" />
                  <path d="M10 17h4" />
                </svg>
              </span>
              <div className={styles.assistantText}>
                <span className={styles.assistantTitle}>Спросить помощника про эту заявку</span>
                <span className={styles.assistantSub}>Инструкции, история, оборудование, контекст</span>
              </div>
              <span className={styles.assistantArrow}>→</span>
            </Link>
          </div>

          {/* Comments Block */}
          <div className={styles.sectionBlock}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Комментарии ({comments.length})</h2>
            </div>

            <div className={styles.commentsList}>
              {comments.length === 0 ? (
                <div className={styles.emptyNote}>Комментариев пока нет</div>
              ) : (
                comments.map((comm) => {
                  const isOwn = user?.id && comm.author_id === user.id;
                  const isEditing = editingCommentId === comm.id;

                  return (
                    <div key={comm.id} className={styles.commentItem}>
                      <div className={styles.commentHeader}>
                        <span className={styles.commentAuthor}>
                          {comm.author_name ? `${comm.author_name} ${comm.author_surname || ""}` : "Пользователь"}
                          {isOwn && <span className={styles.ownBadge}>Вы</span>}
                        </span>
                        <span className={styles.commentTime}>
                          {formatMskDateTime(comm.created_at)}
                        </span>
                      </div>

                      {isEditing ? (
                        <div className={styles.editWrap}>
                          <textarea
                            className={styles.commentInput}
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            rows={2}
                          />
                          <div className={styles.editActions}>
                            <button
                              type="button"
                              className={styles.cancelEditBtn}
                              onClick={() => setEditingCommentId(null)}
                            >
                              Отмена
                            </button>
                            <button
                              type="button"
                              className={styles.saveEditBtn}
                              onClick={() => handleSaveEdit(comm.id)}
                              disabled={isUpdating || !editText.trim()}
                            >
                              Сохранить
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className={styles.commentBody}>
                          <div className={styles.commentText}>{comm.text}</div>
                          {isOwn && (
                            <button
                              type="button"
                              className={styles.editCommentLink}
                              onClick={() => handleStartEdit(comm)}
                            >
                              Редактировать
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* Add comment form */}
            <form onSubmit={handleAddComment} className={styles.addCommentForm}>
              <textarea
                className={styles.commentInput}
                placeholder="Написать заметку или комментарий к заявке..."
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                rows={2}
                maxLength={4000}
              />
              <button
                type="submit"
                className={styles.sendCommentBtn}
                disabled={isAdding || !commentText.trim()}
              >
                {isAdding ? "Отправка..." : "Отправить комментарий"}
              </button>
            </form>
          </div>

          {/* Changes History */}
          <div className={styles.sectionBlock}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>История изменений ({changes.length})</h2>
            </div>
            <ChangeList changes={changes} />
          </div>
        </div>
      </div>
    </div>
  );
}
