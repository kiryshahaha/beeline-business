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

  const isClosed = currentStatus === "completed" || currentStatus === "wont_fix";
  const ticketAreaId = ticket?.service_area_id ?? ticket?.location?.service_area_id;
  const ticketBrigadeId = ticket?.brigade_id;

  const eligibleWorkers = useMemo(() => {
    // Предлагаем только инженеров, относящихся к участку / бригаде этой заявки
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

  const candidateWorkerIds = useMemo(() => {
    return eligibleWorkers.map((w) => w.id).join(",");
  }, [eligibleWorkers]);

  // Глубокая валидация движком планирования бэкенда: занятость, пересечение заявок, навыки, склад
  const { data: eligibilityMap = {}, isLoading: isLoadingEligibility } = useQuery({
    queryKey: ["ticketEligibleWorkers", ticket?.id, candidateWorkerIds],
    enabled: !!ticket?.id && eligibleWorkers.length > 0 && !isClosed,
    queryFn: async () => {
      const results = {};
      await Promise.all(
        eligibleWorkers.map(async (w) => {
          try {
            const res = await apiFetch(`/tickets/${ticket.id}/assign/preview`, {
              method: "POST",
              body: JSON.stringify({ worker_id: w.id }),
            });
            if (res.ok) {
              const data = await res.json();
              const firstViolation = data.violations?.[0];
              results[w.id] = {
                is_eligible: Boolean(data.is_eligible),
                violations: data.violations || [],
                reason: firstViolation?.message || (data.is_eligible ? null : "Ограничение планирования"),
              };
            } else {
              const err = await res.json().catch(() => ({}));
              results[w.id] = {
                is_eligible: false,
                reason: err.detail || "Недоступен",
              };
            }
          } catch {
            results[w.id] = { is_eligible: false, reason: "Ошибка связи" };
          }
        })
      );
      return results;
    },
    staleTime: 15000,
  });

  const HARD_BLOCKING_CODES = useMemo(() => [
    "worker_offline",
    "worker_archived",
    "worker_unavailable",
    "working_on_route_date",
    "service_area_mismatch",
    "service_area_unknown",
    "brigade_mismatch",
    "brigade_resolution_required",
    "missing_skill",
    "equipment_not_reserved",
    "stock_inconsistent",
    "invalid_worker_role",
    "required_transport_mismatch",
  ], []);

  const availableWorkers = useMemo(() => {
    return eligibleWorkers.filter((w) => {
      if (assignedWorkerId && Number(w.id) === Number(assignedWorkerId)) return true;
      if (isLoadingEligibility && Object.keys(eligibilityMap).length === 0) {
        return false;
      }
      const status = eligibilityMap[w.id];
      if (!status) return true;
      if (status.is_eligible) return true;
      // Если мастер в смене и с оборудованием, но занят другими задачами — разрешаем назначить
      const violations = status.violations || [];
      const hasHardBlock = violations.some((v) => HARD_BLOCKING_CODES.includes(v.code));
      return !hasHardBlock;
    });
  }, [eligibleWorkers, eligibilityMap, isLoadingEligibility, assignedWorkerId, HARD_BLOCKING_CODES]);

  const unavailableWorkers = useMemo(() => {
    return eligibleWorkers.filter((w) => {
      if (assignedWorkerId && Number(w.id) === Number(assignedWorkerId)) return false;
      const status = eligibilityMap[w.id];
      if (!status) return false;
      const violations = status.violations || [];
      return violations.some((v) => HARD_BLOCKING_CODES.includes(v.code));
    });
  }, [eligibleWorkers, eligibilityMap, assignedWorkerId, HARD_BLOCKING_CODES]);

  const handleAssigneeChange = async (e) => {
    if (isClosed) return;
    const rawVal = e.target.value;
    const workerId = rawVal ? Number(rawVal) : null;
    if (workerId === assignedWorkerId || isUpdatingAssignee) return;

    setIsUpdatingAssignee(true);
    setErrorMessage(null);
    setActionMessage(null);

    try {
      if (workerId) {
        const selectedWorker = eligibleWorkers.find((w) => w.id === workerId) || workers.find((w) => w.id === workerId);
        if (selectedWorker?.brigade_id && ticket?.brigade_id !== selectedWorker.brigade_id) {
          await apiFetch(`/tickets/${ticket.id}/brigade`, {
            method: "PUT",
            body: JSON.stringify({ brigade_id: selectedWorker.brigade_id }),
          }).catch(() => null);
        }
      }

      let res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
        method: "PUT",
        body: JSON.stringify({
          worker_id: workerId,
          is_pinned: true,
        }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        const eqViolation = errorData?.detail?.violations?.find((v) => v.code === "equipment_not_reserved");
        if (eqViolation && eqViolation.ids?.appliance_ids?.length) {
          const appId = eqViolation.ids.appliance_ids[0];
          const selectedWorker = workers.find((w) => w.id === workerId);
          const officeId = selectedWorker?.office_id || 10;
          await apiFetch(`/tickets/${ticket.id}/appliances`, {
            method: "POST",
            body: JSON.stringify({ appliance_id: appId, quantity: 1, office_id: officeId }),
          }).catch(() => null);

          // Повторяем попытку назначения после выделения оборудования
          res = await apiFetch(`/tickets/${ticket.id}/assignees`, {
            method: "PUT",
            body: JSON.stringify({
              worker_id: workerId,
              is_pinned: true,
            }),
          });
        }

        if (!res.ok) {
          const retryErrData = await res.json().catch(() => errorData);
          let msg = null;
          if (retryErrData?.detail?.violations?.length) {
            msg = retryErrData.detail.violations.map((v) => v.message).filter(Boolean).join(" · ");
          } else if (typeof retryErrData?.detail === "string") {
            msg = retryErrData.detail;
          } else if (retryErrData?.detail?.message) {
            msg = retryErrData.detail.message;
          } else if (retryErrData?.message) {
            msg = retryErrData.message;
          }
          throw new Error(msg || "Не удалось назначить исполнителя");
        }
      }

      await res.json();
      setAssignedWorkerId(workerId || "");
      setActionMessage(workerId ? "Инженер назначен" : "Назначение снято");
      setTimeout(() => setActionMessage(null), 3000);

      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
      queryClient.invalidateQueries({ queryKey: ["routes"] });
      queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
    } catch (err) {
      setErrorMessage(err.message || "Ошибка назначения мастера");
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
                disabled={isUpdatingAssignee || isClosed || (isLoadingEligibility && Object.keys(eligibilityMap).length === 0)}
              >
                <option value="">Не назначен (в пуле)</option>
                {isLoadingEligibility && Object.keys(eligibilityMap).length === 0 ? (
                  <option disabled>⏳ Проверка доступности инженеров...</option>
                ) : (
                  availableWorkers.map((w) => {
                    const fullName = [w.surname, w.name, w.lastname].filter(Boolean).join(" ") || `Инженер #${w.id}`;
                    const brigadeSuffix = w.brigade_name ? ` · ${w.brigade_name}` : "";
                    const status = eligibilityMap[w.id];
                    const subText = status && !status.is_eligible ? " (в смене, есть задачи)" : "";
                    return (
                      <option key={w.id} value={w.id}>
                        {fullName}{brigadeSuffix}{subText}
                      </option>
                    );
                  })
                )}
              </select>
              {isClosed && (
                <div className={styles.assignDisabledNote}>
                  {currentStatus === "completed"
                    ? "Заявка выполнена — назначение недоступно"
                    : "Заявка отменена — назначение недоступно"}
                </div>
              )}
              {isLoadingEligibility && Object.keys(eligibilityMap).length === 0 && (
                <div className={styles.assignDisabledNote} style={{ color: "#F59E0B" }}>
                  Проверка графиков и занятости инженеров...
                </div>
              )}
              {!isClosed && !isLoadingEligibility && availableWorkers.length === 0 && (
                <div className={styles.assignDisabledNote}>
                  Нет свободных воркеров
                </div>
              )}
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
