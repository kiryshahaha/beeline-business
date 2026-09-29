"use client";

import { useState, useEffect, useMemo } from "react";
import { Popup } from "@vis.gl/react-maplibre";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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

function formatApiError(errorData, fallback = "Ошибка операции") {
  if (!errorData) return fallback;
  if (typeof errorData === "string") return errorData;
  if (typeof errorData.detail === "string") return errorData.detail;
  if (Array.isArray(errorData.detail?.violations)) {
    return errorData.detail.violations.map((v) => v.message || v.code).filter(Boolean).join(" · ");
  }
  if (Array.isArray(errorData.violations)) {
    return errorData.violations.map((v) => v.message || v.code).filter(Boolean).join(" · ");
  }
  if (errorData.detail?.message) return errorData.detail.message;
  if (errorData.message) return errorData.message;
  return fallback;
}

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
  const [selectedCandidateId, setSelectedCandidateId] = useState(ticket?.assigned_worker_id || "");
  const [isPinned, setIsPinned] = useState(Boolean(ticket?.is_pinned));
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [isUpdatingAssignee, setIsUpdatingAssignee] = useState(false);
  const [actionMessage, setActionMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    queueMicrotask(() => {
      setCurrentStatus(ticket?.status || "planned");
      setAssignedWorkerId(ticket?.assigned_worker_id || "");
      setSelectedCandidateId(ticket?.assigned_worker_id || "");
      setIsPinned(Boolean(ticket?.is_pinned));
      setActionMessage(null);
      setErrorMessage(null);
    });
  }, [ticket]);

  const isClosed = currentStatus === "completed" || currentStatus === "wont_fix";
  const ticketAreaId = ticket?.service_area_id ?? ticket?.location?.service_area_id;
  const ticketBrigadeId = ticket?.brigade_id;

  const eligibleWorkers = useMemo(() => {
    const filtered = workers.filter((w) => {
      if (ticketBrigadeId && w.brigade_id && Number(w.brigade_id) !== Number(ticketBrigadeId)) {
        return false;
      }
      if (ticketAreaId && w.service_area_id && Number(w.service_area_id) !== Number(ticketAreaId)) {
        return false;
      }
      return true;
    });

    return filtered.sort((a, b) => {
      const onlineA = a.worker_profile?.is_on_line ? 1 : 0;
      const onlineB = b.worker_profile?.is_on_line ? 1 : 0;
      if (onlineB !== onlineA) return onlineB - onlineA;
      const nameA = [a.surname, a.name].filter(Boolean).join(" ");
      const nameB = [b.surname, b.name].filter(Boolean).join(" ");
      return nameA.localeCompare(nameB, "ru");
    });
  }, [workers, ticketAreaId, ticketBrigadeId]);

  // On-demand preview: проверяем доступность только выбранного кандидата
  const candidateWorkerIdNum = selectedCandidateId ? Number(selectedCandidateId) : null;
  const isCandidateSelected = candidateWorkerIdNum && candidateWorkerIdNum !== Number(assignedWorkerId);

  const {
    data: previewData,
    isLoading: isLoadingPreview,
    error: previewError,
  } = useQuery({
    queryKey: ["assignPreview", ticket?.id, candidateWorkerIdNum],
    queryFn: async () => {
      const res = await apiFetch(`/tickets/${ticket.id}/assign/preview`, {
        method: "POST",
        body: JSON.stringify({ worker_id: candidateWorkerIdNum }),
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errorData, "Планировщик отклонил назначение"));
      }
      return await res.json();
    },
    enabled: Boolean(ticket?.id && isCandidateSelected && !isClosed),
    staleTime: 30000,
  });

  const invalidateTicketState = () => {
    queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
    queryClient.invalidateQueries({ queryKey: ["tickets"] });
    queryClient.invalidateQueries({ queryKey: ["fastStats"] });
    queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
    queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
    queryClient.invalidateQueries({ queryKey: ["tickets-summary"] });
    queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
    queryClient.invalidateQueries({ queryKey: ["routes"] });
  };

  const handleStatusChange = async (newStatus) => {
    if (newStatus === currentStatus || isUpdatingStatus) return;
    setIsUpdatingStatus(true);
    setErrorMessage(null);
    setActionMessage(null);

    let cancelReason = null;
    if (newStatus === "wont_fix") {
      cancelReason = window.prompt("Укажите причину отмены заявки:", "Отменено диспетчером");
      if (cancelReason === null) {
        setIsUpdatingStatus(false);
        return;
      }
    }

    try {
      const payload = {
        status: newStatus,
        reason: cancelReason || undefined,
        expected_revision: ticket.revision || undefined,
      };

      const res = await apiFetch(`/tickets/${ticket.id}/status`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errorData, "Не удалось изменить статус заявки"));
      }

      const updated = await res.json();
      setCurrentStatus(updated.status || newStatus);
      setActionMessage("Статус обновлен");
      setTimeout(() => setActionMessage(null), 3000);

      invalidateTicketState();
    } catch (err) {
      setErrorMessage(err.message || "Ошибка смены статуса");
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const handleApplyAssignment = async () => {
    if (isClosed || isUpdatingAssignee) return;
    const workerId = candidateWorkerIdNum;
    setIsUpdatingAssignee(true);
    setErrorMessage(null);
    setActionMessage(null);

    try {
      let res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
        method: "PUT",
        body: JSON.stringify({
          worker_id: workerId,
          is_pinned: isPinned,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        const eqViolation = errorData?.detail?.violations?.find(
          (v) => v.code === "equipment_not_reserved"
        );
        if (eqViolation && eqViolation.ids?.appliance_ids?.length) {
          const appId = eqViolation.ids.appliance_ids[0];
          const selectedWorker = workers.find((w) => w.id === workerId);
          const officeId =
            selectedWorker?.worker_profile?.stock_office_id ||
            selectedWorker?.office_id ||
            ticket?.office_id ||
            10;
          await apiFetch(`/tickets/${ticket.id}/appliances`, {
            method: "POST",
            body: JSON.stringify({ appliance_id: appId, quantity: 1, office_id: officeId }),
          }).catch(() => null);

          // Повторяем назначение после выделения оборудования
          res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
            method: "PUT",
            body: JSON.stringify({
              worker_id: workerId,
              is_pinned: isPinned,
            }),
          });
        }

        if (!res.ok) {
          const retryErrData = await res.json().catch(() => errorData);
          throw new Error(formatApiError(retryErrData, "Не удалось назначить исполнителя"));
        }
      }

      await res.json();
      setAssignedWorkerId(workerId || "");
      setSelectedCandidateId(workerId || "");
      setActionMessage("Инженер назначен");
      setTimeout(() => setActionMessage(null), 3000);

      invalidateTicketState();
    } catch (err) {
      setErrorMessage(err.message || "Ошибка назначения мастера");
    } finally {
      setIsUpdatingAssignee(false);
    }
  };

  const handleUnassign = async () => {
    if (isClosed || isUpdatingAssignee) return;
    setIsUpdatingAssignee(true);
    setErrorMessage(null);
    setActionMessage(null);

    try {
      const res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
        method: "PUT",
        body: JSON.stringify({
          worker_id: null,
          is_pinned: false,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(formatApiError(errorData, "Не удалось снять назначение"));
      }

      await res.json();
      setAssignedWorkerId("");
      setSelectedCandidateId("");
      setIsPinned(false);
      setActionMessage("Назначение снято");
      setTimeout(() => setActionMessage(null), 3000);

      invalidateTicketState();
    } catch (err) {
      setErrorMessage(err.message || "Ошибка при снятии назначения");
    } finally {
      setIsUpdatingAssignee(false);
    }
  };

  if (!ticket) return null;

  const popupLongitude = Number(ticket.location?.longitude ?? ticket.longitude);
  const popupLatitude = Number(ticket.location?.latitude ?? ticket.latitude);

  if (!Number.isFinite(popupLongitude) || !Number.isFinite(popupLatitude)) {
    return null;
  }

  const assignedWorker = workers.find((w) => Number(w.id) === Number(assignedWorkerId));
  const candidateWorker = workers.find((w) => Number(w.id) === candidateWorkerIdNum);

  return (
    <Popup
      longitude={popupLongitude}
      latitude={popupLatitude}
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
              Окно визита:{" "}
              {new Date(ticket.visit_window_start).toLocaleTimeString("ru-RU", {
                timeZone: "Europe/Moscow",
                hour: "2-digit",
                minute: "2-digit",
              })}
              {ticket.visit_window_end && (
                ` — ${new Date(ticket.visit_window_end).toLocaleTimeString("ru-RU", {
                  timeZone: "Europe/Moscow",
                  hour: "2-digit",
                  minute: "2-digit",
                })}`
              )}
            </span>
          </p>
        )}

        {/* Индикатор загрузки автомаршрута */}
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
            <span className={styles.actionSectionTitle}>Исполнитель</span>
            <div className={styles.assignSelectWrapper}>
              <select
                className={styles.assignSelect}
                value={selectedCandidateId}
                onChange={(e) => {
                  setSelectedCandidateId(e.target.value);
                  setErrorMessage(null);
                }}
                disabled={isUpdatingAssignee || isClosed}
              >
                <option value="">Не назначен (в пуле)</option>
                {eligibleWorkers.map((w) => {
                  const fullName = [w.surname, w.name, w.lastname].filter(Boolean).join(" ") || `Инженер #${w.id}`;
                  const brigadeSuffix = w.brigade_name ? ` · ${w.brigade_name}` : "";
                  const isCurrent = Number(w.id) === Number(assignedWorkerId);
                  return (
                    <option key={w.id} value={w.id}>
                      {fullName}{brigadeSuffix}{isCurrent ? " (текущий)" : ""}
                    </option>
                  );
                })}
              </select>

              {isClosed && (
                <div className={styles.assignDisabledNote}>
                  {currentStatus === "completed"
                    ? "Заявка выполнена — изменение исполнителя недоступно"
                    : "Заявка отменена — изменение исполнителя недоступно"}
                </div>
              )}

              {/* Текущее назначение */}
              {!isCandidateSelected && assignedWorker && !isClosed && (
                <div style={{ marginTop: 6 }}>
                  <button
                    type="button"
                    className={styles.assignCancelBtn}
                    onClick={handleUnassign}
                    disabled={isUpdatingAssignee}
                  >
                    {isUpdatingAssignee ? "Снятие..." : "Снять назначение"}
                  </button>
                </div>
              )}

              {/* On-demand валидация выбранного кандидата */}
              {isCandidateSelected && !isClosed && (
                <div>
                  {isLoadingPreview && (
                    <div className={styles.assignPreviewBox}>
                      <span className={styles.assignPreviewTitle} style={{ color: "#FFC800" }}>
                        ⏳ Оценка влияния на маршрут OR-Tools...
                      </span>
                    </div>
                  )}

                  {!isLoadingPreview && previewError && (
                    <div className={`${styles.assignPreviewBox} ${styles.assignPreviewIneligible}`}>
                      <div className={styles.assignPreviewTitle} style={{ color: "#FF453A" }}>
                        ✕ Ошибка проверки кандидата
                      </div>
                      <div>{previewError.message}</div>
                    </div>
                  )}

                  {!isLoadingPreview && previewData && (
                    <div
                      className={`${styles.assignPreviewBox} ${
                        previewData.is_eligible ? styles.assignPreviewEligible : styles.assignPreviewIneligible
                      }`}
                    >
                      <div
                        className={styles.assignPreviewTitle}
                        style={{ color: previewData.is_eligible ? "#30D158" : "#FF453A" }}
                      >
                        {previewData.is_eligible ? "✓ Подходит для назначения" : "✕ Ограничение планировщика"}
                      </div>

                      {previewData.is_eligible ? (
                        <div className={styles.assignPreviewStats}>
                          <span>Сдвиг маршрута: {previewData.route_shift_minutes > 0 ? `+${previewData.route_shift_minutes}` : previewData.route_shift_minutes} мин</span>
                          {previewData.sla_violations_added > 0 ? (
                            <span style={{ color: "#FF9F0A" }}>
                              ⚠ +{previewData.sla_violations_added} нарушений SLA
                            </span>
                          ) : (
                            <span style={{ color: "#30D158" }}>SLA в норме</span>
                          )}
                        </div>
                      ) : (
                        <div style={{ color: "#FF453A", fontSize: 9.5 }}>
                          {previewData.violations?.map((v) => v.message || v.code).join(" · ") || "Недоступен для назначения"}
                        </div>
                      )}

                      <label className={styles.assignPinnedRow}>
                        <input
                          type="checkbox"
                          className={styles.assignPinnedCheckbox}
                          checked={isPinned}
                          onChange={(e) => setIsPinned(e.target.checked)}
                        />
                        <span>Закрепить заявку (не переносить автопланом)</span>
                      </label>

                      <button
                        type="button"
                        className={styles.assignConfirmBtn}
                        onClick={handleApplyAssignment}
                        disabled={!previewData.is_eligible || isUpdatingAssignee}
                      >
                        {isUpdatingAssignee ? "Назначение..." : `Назначить ${candidateWorker?.surname || "мастера"}`}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {errorMessage && <div className={styles.actionErrorMsg}>{errorMessage}</div>}
        </div>
      </div>
    </Popup>
  );
}
