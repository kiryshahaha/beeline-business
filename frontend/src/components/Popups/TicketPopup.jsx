"use client";

import { useState, useEffect } from "react";
import { Popup } from "@vis.gl/react-maplibre";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
import styles from "../MapComponent.module.css";
import routeStyles from "../Routes/Routes.module.css";
import { IconPin, IconClock } from "../Markers/MapIcons";

const STATUS_LABELS = {
  planned: "Ожидает",
  in_progress: "В работе",
  completed: "Выполнена",
  wont_fix: "Отменена",
};

export default function TicketPopup({
  ticket,
  workers = [],
  selectedTicketRoute,
  activeLegRoute,
  isLoadingRoute,
  onSelectRouteStop,
  onClose,
}) {
  const queryClient = useQueryClient();
  const [currentStatus, setCurrentStatus] = useState(ticket?.status || "planned");
  const [assignedWorkerId, setAssignedWorkerId] = useState(ticket?.assigned_worker_id || "");
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [isUpdatingAssignee, setIsUpdatingAssignee] = useState(false);
  const [actionMessage, setActionMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    queueMicrotask(() => {
      setCurrentStatus(ticket?.status || "planned");
      setAssignedWorkerId(ticket?.assigned_worker_id || "");
      setActionMessage(null);
      setErrorMessage(null);
    });
  }, [ticket]);

  if (!ticket) return null;

  const handleStatusChange = async (newStatus) => {
    if (newStatus === currentStatus || isUpdatingStatus) return;
    setIsUpdatingStatus(true);
    setErrorMessage(null);
    setActionMessage(null);

    try {
      const res = await apiFetch(`/tickets/${ticket.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Не удалось изменить статус заявки");
      }

      const updated = await res.json();
      setCurrentStatus(updated.status || newStatus);
      setActionMessage("Статус обновлен");
      setTimeout(() => setActionMessage(null), 3000);

      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
      queryClient.invalidateQueries({ queryKey: ["tickets-summary"] });
    } catch (err) {
      setErrorMessage(err.message || "Ошибка смены статуса");
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const handleAssigneeChange = async (e) => {
    const rawVal = e.target.value;
    const workerId = rawVal ? Number(rawVal) : null;
    if (workerId === assignedWorkerId || isUpdatingAssignee) return;

    setIsUpdatingAssignee(true);
    setErrorMessage(null);
    setActionMessage(null);

    try {
      const res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
        method: "PUT",
        body: JSON.stringify({
          worker_id: workerId,
          is_pinned: true,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Не удалось назначить исполнителя");
      }

      const updated = await res.json();
      setAssignedWorkerId(workerId || "");
      setActionMessage(workerId ? "Инженер назначен" : "Назначение снято");
      setTimeout(() => setActionMessage(null), 3000);

      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
    } catch (err) {
      setErrorMessage(err.message || "Ошибка назначения мастера");
    } finally {
      setIsUpdatingAssignee(false);
    }
  };

  return (
    <Popup
      longitude={ticket.location?.longitude}
      latitude={ticket.location?.latitude}
      offset={28}
      maxWidth="350px"
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <div className={styles.popupHeader}>
          <span className={styles.popupEyebrow}>Заявка #{ticket.id}</span>
          <span className={`${styles.status} ${styles[`status_${currentStatus}`]}`}>
            {STATUS_LABELS[currentStatus] || currentStatus}
          </span>
        </div>

        <h3 className={styles.popupTitle}>{ticket.title}</h3>
        <p className={styles.popupAddress}>
          <IconPin size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
          <span>{ticket.location?.address || "Адрес не указан"}</span>
        </p>

        <p className={styles.popupCoordinates}>
          {Number(ticket.location?.latitude).toFixed(5)}, {Number(ticket.location?.longitude).toFixed(5)}
        </p>

        <div className={styles.popupMeta}>
          {ticket.work_type && <span className={styles.popupTag}>{ticket.work_type}</span>}
          {ticket.urgency && <span className={styles.popupTag}>{ticket.urgency}</span>}
        </div>

        {ticket.visit_window_start && (
          <p className={styles.popupTime}>
            <IconClock size={13} style={{ flexShrink: 0, opacity: 0.7 }} />
            <span>
              Окно визита: {new Date(ticket.visit_window_start).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
              {ticket.visit_window_end && (
                ` — ${new Date(ticket.visit_window_end).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`
              )}
            </span>
          </p>
        )}

        {/* Индикатор загрузки реалистичного автомаршрута */}
        {isLoadingRoute && (
          <div className={styles.routeLegBox}>
            <div className={styles.routeLegLoading}>
              <span className={styles.routeSpinner} />
              <span>Построение маршрута по дорогам...</span>
            </div>
          </div>
        )}

        {/* Реалистичный дорожный сегмент от предыдущей точки */}
        {!isLoadingRoute && activeLegRoute && (
          <div className={styles.routeLegBox}>
            <div className={styles.routeLegHeader}>
              <span className={styles.routeLegBadge}>Маршрут к заявке</span>
              <span className={styles.routeLegStats}>
                {activeLegRoute.distanceKm} км · ~{activeLegRoute.durationMin} мин
              </span>
            </div>
            <div className={styles.routeLegDetails}>
              <div className={styles.routeLegStep}>
                <span className={styles.routeLegStepDot} style={{ background: "#9CA3AF" }} />
                <span className={styles.routeLegStepText}>
                  От: <strong>{activeLegRoute.origin?.label || "Предыдущая точка"}</strong>
                </span>
              </div>
              <div className={styles.routeLegStep}>
                <span className={styles.routeLegStepDot} style={{ background: "#FFC800" }} />
                <span className={styles.routeLegStepText}>
                  До: <strong>{activeLegRoute.destination?.label || `Заявка #${ticket.id}`}</strong>
                </span>
              </div>
            </div>
          </div>
        )}

        {selectedTicketRoute && (
          <button
            type="button"
            className={routeStyles.focusRouteBtn}
            onClick={() => {
              onSelectRouteStop(selectedTicketRoute.route, selectedTicketRoute.stop);
            }}
          >
            В маршруте #{selectedTicketRoute.route.route_number || 1} (Ост. #{selectedTicketRoute.stop.sequence}) →
          </button>
        )}

        {/* Панель действий диспетчера: сменить статус / назначить инженера */}
        <div className={styles.actionSection}>
          <div className={styles.actionSectionHeader}>
            <span className={styles.actionSectionTitle}>Статус выполнения</span>
            {actionMessage && <span className={styles.actionSuccessMsg}>{actionMessage}</span>}
          </div>

          <div className={styles.statusButtonGroup}>
            <button
              type="button"
              className={`${styles.statusActionBtn} ${currentStatus === "in_progress" ? styles.statusActionBtnActive : ""}`}
              onClick={() => handleStatusChange("in_progress")}
              disabled={isUpdatingStatus || currentStatus === "in_progress"}
            >
              В работу
            </button>
            <button
              type="button"
              className={`${styles.statusActionBtn} ${currentStatus === "completed" ? styles.statusActionBtnActive : ""}`}
              onClick={() => handleStatusChange("completed")}
              disabled={isUpdatingStatus || currentStatus === "completed"}
            >
              Выполнена
            </button>
            <button
              type="button"
              className={`${styles.statusActionBtn} ${currentStatus === "wont_fix" ? styles.statusActionBtnActive : ""}`}
              onClick={() => handleStatusChange("wont_fix")}
              disabled={isUpdatingStatus || currentStatus === "wont_fix"}
            >
              Отменить
            </button>
          </div>

          <div className={styles.assignSection}>
            <span className={styles.actionSectionTitle}>Назначить инженера</span>
            <div className={styles.assignSelectWrapper}>
              <select
                className={styles.assignSelect}
                value={assignedWorkerId}
                onChange={handleAssigneeChange}
                disabled={isUpdatingAssignee}
              >
                <option value="">Не назначен (в пуле)</option>
                {workers.map((w) => {
                  const name = [w.surname, w.name].filter(Boolean).join(" ") || `Инженер #${w.id}`;
                  const isOnline = w.worker_profile?.is_on_line;
                  return (
                    <option key={w.id} value={w.id}>
                      {name} {isOnline ? "(на линии)" : "(офлайн)"}
                    </option>
                  );
                })}
              </select>
            </div>
          </div>

          {errorMessage && (
            <div className={styles.actionErrorMsg}>{errorMessage}</div>
          )}
        </div>
      </div>
    </Popup>
  );
}
