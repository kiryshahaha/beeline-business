"use client";

import { useState, useMemo } from "react";
import styles from "./Routes.module.css";
import { useCalculateRoute } from "@/hooks/useRoutes";
import {
  calculateRouteDistanceKm,
  calculateShiftTimings,
  resolveStopDetails,
} from "./routeUtils";
import {
  IconCar,
  IconBicycle,
  IconWalk,
  IconOffice,
  IconPin,
  IconMap,
  IconWrench,
  IconStartFlag,
  IconFinishFlag,
  IconChevronLeft,
  IconChevronRight,
  IconChevronDown,
  IconChevronUp,
  IconClose,
} from "../Markers/MapIcons";

export default function RouteFloatingCard({
  selectedRoute,
  allRoutes = [],
  worker,
  selectedObject,
  tickets = [],
  offices = [],
  locationById,
  onSelectStop,
  onSelectRoute,
  onFocusRoute,
  onClose,
}) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [optimizedNotice, setOptimizedNotice] = useState(null);
  const calculateRoute = useCalculateRoute();

  const stops = useMemo(() => selectedRoute?.stops || [], [selectedRoute]);
  const totalStops = stops.length;

  // Расчет метрик дистанции и времени смены
  const distanceKm = useMemo(
    () => calculateRouteDistanceKm(selectedRoute),
    [selectedRoute],
  );

  const shiftTimings = useMemo(
    () => calculateShiftTimings(stops),
    [stops],
  );

  const ticketsCount = useMemo(
    () => stops.filter((s) => s.ticket_id).length,
    [stops],
  );

  // Определение индекса текущего маршрута для переключателя
  const currentRouteIndex = useMemo(() => {
    if (!selectedRoute || !allRoutes.length) return -1;
    return allRoutes.findIndex((r) => r.id === selectedRoute.id);
  }, [allRoutes, selectedRoute]);

  if (!selectedRoute) return null;

  const workerFullName = worker
    ? [worker.surname, worker.name, worker.lastname].filter(Boolean).join(" ")
    : `Инженер #${selectedRoute.worker_id}`;

  const transportType = worker?.worker_profile?.transport_type || "car";
  const isOnline = worker?.worker_profile?.is_on_line !== false;
  const transportLabel =
    transportType === "car"
      ? "Автомобиль"
      : transportType === "bicycle"
        ? "Велосипед"
        : transportType === "walking"
          ? "Пешком"
          : "Транспорт";

  const brigadeInfo = worker?.worker_profile?.brigade_id
    ? `Бригада #${worker.worker_profile.brigade_id}`
    : "Дежурная смена";

  // Навигация между маршрутами (Cycler)
  const handlePrevRoute = () => {
    if (allRoutes.length <= 1 || currentRouteIndex === -1) return;
    const prevIdx = (currentRouteIndex - 1 + allRoutes.length) % allRoutes.length;
    onSelectRoute?.(allRoutes[prevIdx]);
  };

  const handleNextRoute = () => {
    if (allRoutes.length <= 1 || currentRouteIndex === -1) return;
    const nextIdx = (currentRouteIndex + 1) % allRoutes.length;
    onSelectRoute?.(allRoutes[nextIdx]);
  };

  // Оптимизация маршрута через бэкенд
  const handleOptimize = async () => {
    setIsOptimizing(true);
    setOptimizedNotice(null);
    try {
      if (stops.length >= 2) {
        const first = stops[0];
        const last = stops[stops.length - 1];
        const mode =
          transportType === "bicycle"
            ? "bicycle"
            : transportType === "walking"
              ? "walking"
              : "drive";

        const res = await calculateRoute.mutateAsync({
          origin: { latitude: first.latitude, longitude: first.longitude },
          destination: { latitude: last.latitude, longitude: last.longitude },
          mode,
        });

        const dist = (res.distance_meters / 1000).toFixed(1);
        const dur = Math.round(res.duration_seconds / 60);
        setOptimizedNotice(`Рассчитано через бэкенд: ${dist} км, ~${dur} мин в пути`);
      } else {
        setOptimizedNotice("Маршрут актуален");
      }
    } catch (err) {
      setOptimizedNotice(err.message || "Ошибка расчета маршрута");
    } finally {
      setIsOptimizing(false);
    }
  };

  // Определение текущей активной остановки
  const currentStopIndex = stops.findIndex(
    (s) => s.sequence === selectedObject?.stopSequence,
  );

  const handlePrevStop = () => {
    if (currentStopIndex > 0) {
      onSelectStop(selectedRoute, stops[currentStopIndex - 1]);
    } else if (currentStopIndex === -1 && stops.length > 0) {
      onSelectStop(selectedRoute, stops[0]);
    }
  };

  const handleNextStop = () => {
    if (currentStopIndex >= 0 && currentStopIndex < stops.length - 1) {
      onSelectStop(selectedRoute, stops[currentStopIndex + 1]);
    } else if (currentStopIndex === -1 && stops.length > 0) {
      onSelectStop(selectedRoute, stops[0]);
    }
  };

  // 1. Свернутый режим (Compact Bar)
  if (isCollapsed) {
    return (
      <div className={`${styles.routeFloatingCard} ${styles.routeFloatingCard_collapsed}`}>
        <div
          className={styles.collapsedBar}
          onClick={() => setIsCollapsed(false)}
          title="Развернуть маршрутный лист"
        >
          <div className={styles.collapsedInfo}>
            <span
              className={styles.routeColorDot}
              style={{ backgroundColor: selectedRoute.color }}
            />
            <span className={styles.collapsedName}>
              #{selectedRoute.route_number || 1} • {workerFullName}
            </span>
            <span className={styles.collapsedMetrics}>
              ({totalStops} ост. • {distanceKm} км)
            </span>
          </div>
          <div className={styles.headerControls}>
            <button
              type="button"
              className={styles.controlBtn}
              onClick={(e) => {
                e.stopPropagation();
                setIsCollapsed(false);
              }}
              aria-label="Развернуть"
              title="Развернуть"
            >
              <IconChevronUp size={11} />
            </button>
            <button
              type="button"
              className={styles.controlBtn}
              onClick={(e) => {
                e.stopPropagation();
                onClose?.();
              }}
              aria-label="Закрыть"
              title="Закрыть"
            >
              <IconClose size={10} />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 2. Развернутый режим (Full Inspector)
  return (
    <div className={styles.routeFloatingCard}>
      {/* 2.1. Шапка с переключателем маршрутов */}
      <div className={styles.routeCardHeader}>
        <div className={styles.headerLeft}>
          <span
            className={styles.routeBadge}
            style={{
              backgroundColor: `${selectedRoute.color}25`,
              color: selectedRoute.color,
              border: `1px solid ${selectedRoute.color}60`,
            }}
          >
            Маршрут #{selectedRoute.route_number || 1}
          </span>
          {selectedRoute.day_revision != null && (
            <span className={styles.revisionTag}>rev.{selectedRoute.day_revision}</span>
          )}
        </div>

        {allRoutes.length > 1 && (
          <div className={styles.routeCycler}>
            <button
              type="button"
              className={styles.cyclerBtn}
              onClick={handlePrevRoute}
              title="Предыдущий маршрут"
              aria-label="Предыдущий маршрут"
            >
              <IconChevronLeft size={11} />
            </button>
            <span className={styles.cyclerText}>
              {currentRouteIndex >= 0 ? `${currentRouteIndex + 1} / ${allRoutes.length}` : "1"}
            </span>
            <button
              type="button"
              className={styles.cyclerBtn}
              onClick={handleNextRoute}
              title="Следующий маршрут"
              aria-label="Следующий маршрут"
            >
              <IconChevronRight size={11} />
            </button>
          </div>
        )}

        <div className={styles.headerControls}>
          <button
            type="button"
            className={styles.controlBtn}
            onClick={() => setIsCollapsed(true)}
            title="Свернуть"
            aria-label="Свернуть панель маршрута"
          >
            <IconChevronDown size={11} />
          </button>
          <button
            type="button"
            className={styles.controlBtn}
            onClick={onClose}
            title="Закрыть"
            aria-label="Закрыть панель маршрута"
          >
            <IconClose size={10} />
          </button>
        </div>
      </div>

      {/* 2.2. Карточка исполнителя */}
      <div className={styles.workerSection}>
        <div className={styles.workerAvatar}>
          {transportType === "bicycle" ? (
            <IconBicycle size={20} />
          ) : transportType === "walking" ? (
            <IconWalk size={20} />
          ) : (
            <IconCar size={20} />
          )}
        </div>
        <div className={styles.workerInfo}>
          <div className={styles.workerName}>{workerFullName}</div>
          <div className={styles.workerSub}>
            <span
              className={`${styles.statusDot} ${isOnline ? styles.statusDotOnline : styles.statusDotOffline}`}
            />
            <span>{isOnline ? "На линии" : "Офлайн"}</span>
            <span>•</span>
            <span>{transportLabel}</span>
            <span>•</span>
            <span>{brigadeInfo}</span>
          </div>
        </div>
      </div>

      {/* 2.3. Сетка ключевых показателей (KPI) */}
      <div className={styles.kpiGrid}>
        <div className={styles.kpiCard}>
          <div className={styles.kpiLabel}>Остановок</div>
          <div className={styles.kpiValue}>{totalStops}</div>
          <div className={styles.kpiSub}>{ticketsCount} заявок</div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.kpiLabel}>Дистанция</div>
          <div className={styles.kpiValue}>{distanceKm} км</div>
          <div className={styles.kpiSub}>по дорогам</div>
        </div>
        <div className={styles.kpiCard}>
          <div className={styles.kpiLabel}>Смена</div>
          <div className={styles.kpiValue}>{shiftTimings.totalDurationHours}</div>
          <div className={styles.kpiSub}>{shiftTimings.timeRange}</div>
        </div>
      </div>

      {/* 2.4. Панель быстрых действий */}
      <div className={styles.actionsRow}>
        <button
          type="button"
          className={`${styles.actionBtn} ${styles.actionBtnFocus}`}
          onClick={() => onFocusRoute?.(selectedRoute)}
          title="Вместить весь маршрут в область видимости"
        >
          <IconMap size={13} />
          <span>Весь маршрут</span>
        </button>
        <button
          type="button"
          className={`${styles.actionBtn} ${styles.actionBtnOptimize}`}
          onClick={handleOptimize}
          disabled={isOptimizing}
          title="Пересчитать оптимальный порядок визитов через алгоритм бэкенда"
        >
          <IconWrench size={13} />
          <span>{isOptimizing ? "Расчет..." : "Оптимизировать"}</span>
        </button>
      </div>

      {optimizedNotice && (
        <div className={styles.optimizedNotice}>{optimizedNotice}</div>
      )}

      {/* 2.5. Маршрутный лист (Таймлайн остановок) */}
      <div className={styles.timelineHeader}>
        <span>Маршрутный лист</span>
        <span>{totalStops} точек</span>
      </div>

      <div className={styles.timelineList}>
        {stops.map((stop, idx) => {
          const isStopActive = selectedObject?.stopSequence === stop.sequence;
          const {
            isStart,
            isFinish,
            title,
            address,
            ticket,
            arrivalFormatted,
          } = resolveStopDetails(stop, idx, totalStops, tickets, offices, locationById);

          return (
            <div
              key={stop.sequence}
              className={`${styles.timelineItem} ${isStopActive ? styles.timelineItemActive : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                onSelectStop(selectedRoute, stop);
              }}
            >
              <div
                className={`${styles.timelineBadge} ${
                  isStopActive
                    ? styles.timelineBadgeActive
                    : isStart
                      ? styles.timelineBadgeStart
                      : isFinish
                        ? styles.timelineBadgeFinish
                        : ""
                }`}
                style={
                  !isStopActive && !isStart && !isFinish
                    ? { backgroundColor: `${selectedRoute.color}25`, color: selectedRoute.color }
                    : undefined
                }
              >
                {isStart ? (
                  <IconStartFlag size={12} />
                ) : isFinish ? (
                  <IconFinishFlag size={12} />
                ) : (
                  stop.sequence
                )}
              </div>

              <div className={styles.timelineContent}>
                <div className={styles.timelineTitle}>{title}</div>
                <div className={styles.timelineAddress}>
                  {isStart || isFinish ? <IconOffice size={12} /> : <IconPin size={12} />}
                  <span>{address}</span>
                </div>

                <div className={styles.timelineMeta}>
                  <span className={styles.timelineTime}>
                    {arrivalFormatted ? `Прибытие: ${arrivalFormatted}` : `Остановка #${stop.sequence}`}
                    {stop.effective_service_minutes ? ` • ${stop.effective_service_minutes} мин` : ""}
                  </span>

                  {ticket && (
                    <span
                      className={`${styles.timelineTag} ${
                        ticket.priority === 1
                          ? styles.tagUrgent
                          : ticket.status === "in_progress"
                            ? styles.tagProgress
                            : ticket.status === "completed"
                              ? styles.tagCompleted
                              : styles.tagPlanned
                      }`}
                    >
                      {ticket.priority === 1
                        ? "Срочно"
                        : ticket.status === "in_progress"
                          ? "В работе"
                          : ticket.status === "completed"
                            ? "Выполнено"
                            : "План"}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 2.6. Степпер пошагового обхода остановок */}
      <div className={styles.stepperFooter}>
        <button
          type="button"
          className={styles.stepperBtn}
          onClick={handlePrevStop}
          disabled={currentStopIndex <= 0}
          title="Перейти к предыдущей точке маршрута"
        >
          ← Пред. точка
        </button>

        <span className={styles.stepperInfo}>
          {currentStopIndex >= 0
            ? `Точка ${currentStopIndex + 1} из ${totalStops}`
            : `Всего ${totalStops} точек`}
        </span>

        <button
          type="button"
          className={styles.stepperBtn}
          onClick={handleNextStop}
          disabled={currentStopIndex >= totalStops - 1}
          title="Перейти к следующей точке маршрута"
        >
          След. точка →
        </button>
      </div>
    </div>
  );
}
