"use client";
import { useState, useEffect } from "react";
import { Popup } from "@vis.gl/react-maplibre";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
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
  const queryClient = useQueryClient();
  const initialOnline = Boolean(worker?.worker_profile?.is_on_line);
  const [isOnLine, setIsOnLine] = useState(initialOnline);
  const [isUpdating, setIsUpdating] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    queueMicrotask(() => {
      setIsOnLine(Boolean(worker?.worker_profile?.is_on_line));
      setErrorMessage(null);
    });
  }, [worker]);

  if (!worker || worker.location?.longitude == null || worker.location?.latitude == null) return null;

  const fullName = [worker.surname, worker.name, worker.lastname]
    .filter(Boolean)
    .join(" ");

  const transportKey = worker.worker_profile?.transport_type || "car";
  const transportName = TRANSPORT_NAMES[transportKey] || transportKey;

  const address = worker.location.address || (
    [worker.location.city, worker.location.street && `ул. ${worker.location.street}`, worker.location.building_number && `д. ${worker.location.building_number}`]
      .filter(Boolean)
      .join(", ")
  ) || "Адрес базирования не указан";

  const handleToggleLineStatus = async (e) => {
    e.stopPropagation();
    if (isUpdating) return;
    setIsUpdating(true);
    setErrorMessage(null);

    const targetStatus = !isOnLine;
    try {
      const res = await apiFetch(`/workers/${worker.id}/line-status`, {
        method: "PUT",
        body: JSON.stringify({ is_on_line: targetStatus }),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "Не удалось изменить статус мастера");
      }

      setIsOnLine(targetStatus);
      // Инвалидируем кэш для обновления маркеров на карте (FE-04)
      queryClient.invalidateQueries({ queryKey: ["usersList"] });
      queryClient.invalidateQueries({ queryKey: ["fastStats"] });
      queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
    } catch (err) {
      setErrorMessage(err.message || "Ошибка обновления");
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <Popup
      longitude={worker.location.longitude}
      latitude={worker.location.latitude}
      offset={28}
      maxWidth="340px"
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <div className={styles.popupHeader}>
          <span className={styles.popupEyebrow}>Инженер</span>
          <button
            type="button"
            className={`${styles.lineStatusToggleBtn} ${isOnLine ? styles.lineStatusOnline : styles.lineStatusOffline}`}
            onClick={handleToggleLineStatus}
            disabled={isUpdating}
            title={isOnLine ? "Нажмите, чтобы снять с линии" : "Нажмите, чтобы вывести на линию"}
          >
            <span
              className={styles.statusIndicatorDot}
              style={{ background: isOnLine ? "#30D158" : "rgba(255, 255, 255, 0.4)" }}
            />
            <span>{isUpdating ? "Обновление..." : isOnLine ? "На линии" : "Офлайн"}</span>
          </button>
        </div>
        {errorMessage && (
          <div className={styles.actionErrorMsg}>{errorMessage}</div>
        )}

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
