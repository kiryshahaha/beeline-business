"use client";

import { Popup } from "@vis.gl/react-maplibre";
import styles from "../MapComponent.module.css";
import routeStyles from "../Routes/Routes.module.css";
import { IconPin } from "../Markers/MapIcons";

const TRANSPORT_NAMES = {
  car: "Автомобиль",
  bicycle: "Велосипед",
  walking: "Пешком",
  public_transport: "Общ. транспорт",
};

export default function WorkerPopup({
  worker,
  selectedWorkerRoute,
  onSelectRoute,
  onClose,
}) {
  if (!worker || !worker.location) return null;

  const fullName = [worker.surname, worker.name, worker.lastname]
    .filter(Boolean)
    .join(" ");

  const isOnline = worker.worker_profile?.is_on_line;
  const transportKey = worker.worker_profile?.transport_type || "car";
  const transportName = TRANSPORT_NAMES[transportKey] || transportKey;

  const address = worker.location.address || (
    [worker.location.city, worker.location.street && `ул. ${worker.location.street}`, worker.location.building_number && `д. ${worker.location.building_number}`]
      .filter(Boolean)
      .join(", ")
  ) || "Адрес базирования не указан";

  return (
    <Popup
      longitude={worker.location.longitude}
      latitude={worker.location.latitude}
      offset={16}
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <div className={styles.popupHeader}>
          <span className={styles.popupEyebrow}>Инженер</span>
          <span
            className={styles.status}
            style={{
              background: isOnline ? "rgba(48, 209, 88, 0.18)" : "rgba(255, 255, 255, 0.08)",
              color: isOnline ? "#30D158" : "rgba(255, 255, 255, 0.6)",
              border: isOnline ? "1px solid rgba(48, 209, 88, 0.3)" : "1px solid rgba(255, 255, 255, 0.12)",
            }}
          >
            {isOnline ? "На линии" : "Офлайн"}
          </span>
        </div>

        <h3 className={styles.popupTitle}>{fullName}</h3>
        <p className={styles.popupAddress}>
          <IconPin size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
          <span>{address}</span>
        </p>

        <p className={styles.popupCoordinates}>
          {Number(worker.location.latitude).toFixed(5)}, {Number(worker.location.longitude).toFixed(5)}
        </p>

        <div className={styles.popupMeta}>
          <span className={styles.popupTag}>
            {transportName}
          </span>
          {worker.brigade_name ? (
            <span className={styles.popupTag}>{worker.brigade_name}</span>
          ) : (
            <span className={styles.popupTag}>Инженерная служба</span>
          )}
          {worker.worker_profile?.skills?.length > 0 && (
            <span className={styles.popupTag}>
              {worker.worker_profile.skills[0]}
            </span>
          )}
        </div>

        {selectedWorkerRoute && (
          <button
            type="button"
            className={routeStyles.focusRouteBtn}
            onClick={() => onSelectRoute(selectedWorkerRoute)}
          >
            Маршрут #{selectedWorkerRoute.route_number || 1} ({selectedWorkerRoute.stops.length} ост.) →
          </button>
        )}
      </div>
    </Popup>
  );
}
