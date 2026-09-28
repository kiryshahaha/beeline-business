"use client";

import { Popup } from "@vis.gl/react-maplibre";
import popupStyles from "../MapComponent.module.css";
import styles from "./Routes.module.css";
import { IconPin, IconOffice } from "../Markers/MapIcons";

function formatTime(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export default function RouteStopPopup({
  stop,
  totalStops,
  route,
  worker,
  ticket,
  location,
  longitude,
  latitude,
  onClose,
  onSelectNextStop,
  onSelectPrevStop,
}) {
  if (!stop) return null;

  const arrival = formatTime(stop.arrival_at);
  const serviceStart = formatTime(stop.service_start_at);
  const serviceEnd = formatTime(stop.service_end_at);
  const workerFullName = worker
    ? [worker.surname, worker.name, worker.lastname].filter(Boolean).join(" ")
    : `Инженер #${route?.worker_id}`;

  const isStart = stop.sequence === 1 && !stop.ticket_id;
  const isFinish = stop.sequence === totalStops && !stop.ticket_id && totalStops > 1;

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      offset={16}
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={popupStyles.geoPopup}>
        <div className={popupStyles.popupHeader}>
          <span className={popupStyles.popupEyebrow}>
            {isStart ? "Старт маршрута" : isFinish ? "Финиш маршрута" : `Остановка #${stop.sequence} из ${totalStops}`}
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 6px",
              borderRadius: 4,
              backgroundColor: "rgba(255, 200, 0, 0.2)",
              color: "#ffc800",
            }}
          >
            Маршрут #{route?.route_number || 1}
          </span>
        </div>

        {ticket ? (
          <>
            <h3 className={popupStyles.popupTitle}>{ticket.title || `Заявка #${ticket.id}`}</h3>
            <p className={popupStyles.popupAddress}>
              <IconPin size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
              <span>{ticket.location?.address || location?.address || "Адрес не указан"}</span>
            </p>
          </>
        ) : (
          <>
            <h3 className={popupStyles.popupTitle}>{isStart ? "База отправления" : isFinish ? "База возврата" : `Локация #${stop.location_id}`}</h3>
            <p className={popupStyles.popupAddress}>
              <IconOffice size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
              <span>{location?.address || "Адрес базы / офиса"}</span>
            </p>
          </>
        )}

        <p className={popupStyles.popupCoordinates}>
          {Number(latitude).toFixed(5)}, {Number(longitude).toFixed(5)}
        </p>

        <div className={styles.routeTimingBox}>
          {arrival && (
            <div className={styles.timingRow}>
              <span>Прибытие:</span>
              <strong>{arrival}</strong>
            </div>
          )}
          {serviceStart && serviceEnd && (
            <div className={styles.timingRow}>
              <span>Работы:</span>
              <strong>{serviceStart} — {serviceEnd}</strong>
            </div>
          )}
          {stop.effective_service_minutes > 0 && (
            <div className={styles.timingRow}>
              <span>Длительность:</span>
              <span>{stop.effective_service_minutes} мин</span>
            </div>
          )}
          {stop.waiting_minutes > 0 && (
            <div className={styles.timingRow} style={{ color: "#d97706" }}>
              <span>Ожидание окна:</span>
              <span>{stop.waiting_minutes} мин</span>
            </div>
          )}
        </div>

        <div className={popupStyles.popupMeta}>
          <span style={{ fontWeight: 600 }}>{workerFullName}</span>
          {worker?.worker_profile?.transport_type && (
            <span style={{ opacity: 0.8 }}>({worker.worker_profile.transport_type})</span>
          )}
        </div>

        {totalStops > 1 && (
          <div className={styles.stopNavigation}>
            <button
              type="button"
              className={styles.navBtn}
              disabled={stop.sequence <= 1}
              onClick={onSelectPrevStop}
              aria-label="Предыдущая остановка"
            >
              ← Пред.
            </button>
            <span style={{ fontSize: 11, color: "#888" }}>
              {stop.sequence} / {totalStops}
            </span>
            <button
              type="button"
              className={styles.navBtn}
              disabled={stop.sequence >= totalStops}
              onClick={onSelectNextStop}
              aria-label="Следующая остановка"
            >
              След. →
            </button>
          </div>
        )}
      </div>
    </Popup>
  );
}
