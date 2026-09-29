"use client";

import { Popup } from "@vis.gl/react-maplibre";
import popupStyles from "../MapComponent.module.css";
import styles from "./Routes.module.css";
import { IconCalendar } from "../Markers/MapIcons";

export default function RoutePopup({
  route,
  worker,
  coordinates,
  stopsCount,
  onClose,
  onFocusRoute,
}) {
  if (!route || !coordinates) return null;

  const workerName = worker
    ? [worker.surname, worker.name, worker.lastname].filter(Boolean).join(" ")
    : `Инженер #${route.worker_id}`;

  const isCurrent = route.is_current_plan;

  return (
    <Popup
      longitude={coordinates[0]}
      latitude={coordinates[1]}
      offset={28}
      maxWidth="340px"
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={popupStyles.geoPopup}>
        <div className={popupStyles.popupHeader}>
          <span className={popupStyles.popupEyebrow}>
            Маршрут #{route.route_number || 1}
          </span>
          <span
            className={popupStyles.status}
            style={{
              background: isCurrent ? "rgba(48, 209, 88, 0.15)" : "rgba(118, 118, 128, 0.15)",
              color: isCurrent ? "#30D158" : "#888888",
            }}
          >
            {isCurrent === true ? "Актуальный" : isCurrent === false ? "Архивный" : "Сохранён"}
          </span>
        </div>

        <h3 className={popupStyles.popupTitle}>{workerName}</h3>
        <p className={popupStyles.popupAddress}>
          <IconCalendar size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
          <span>Дата: {new Date(route.route_date).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}</span>
        </p>

        <div className={styles.routeMetricsRow}>
          <div className={styles.routeMetric}>
            <span className={styles.routeMetricLabel}>Остановок</span>
            <span className={styles.routeMetricValue}>{stopsCount}</span>
          </div>
          {route.day_revision != null && (
            <div className={styles.routeMetric}>
              <span className={styles.routeMetricLabel}>Ревизия</span>
              <span className={styles.routeMetricValue}>rev.{route.day_revision}</span>
            </div>
          )}
        </div>

        {onFocusRoute && (
          <button
            type="button"
            className={styles.focusRouteBtn}
            onClick={onFocusRoute}
          >
            Показать маршрут полностью
          </button>
        )}
      </div>
    </Popup>
  );
}
