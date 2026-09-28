"use client";

import { Popup } from "@vis.gl/react-maplibre";
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
  selectedTicketRoute,
  onSelectRouteStop,
  onClose,
}) {
  if (!ticket) return null;

  return (
    <Popup
      longitude={ticket.location?.longitude}
      latitude={ticket.location?.latitude}
      offset={16}
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <div className={styles.popupHeader}>
          <span className={styles.popupEyebrow}>Заявка #{ticket.id}</span>
          <span className={`${styles.status} ${styles[`status_${ticket.status}`]}`}>
            {STATUS_LABELS[ticket.status] || ticket.status}
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
      </div>
    </Popup>
  );
}
