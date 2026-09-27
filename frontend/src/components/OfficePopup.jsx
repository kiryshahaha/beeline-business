import { Popup } from "@vis.gl/react-maplibre";
import styles from "./MapComponent.module.css";

export default function OfficePopup({ data, longitude, latitude, onClose }) {
  if (!data) return null;

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <span className={styles.popupEyebrow}>Офис #{data.office_id ?? data.id}</span>
        <h3>{data.office_name || "Офис обслуживания"}</h3>
        <p>{data.address || "Адрес не указан"}</p>
        <p className={styles.coordinates}>{Number(latitude).toFixed(5)}, {Number(longitude).toFixed(5)}</p>
        <div className={styles.popupMeta}>
          {data.city && <span>{data.city}</span>}
          {data.district && <span>{data.district}</span>}
        </div>
      </div>
    </Popup>
  );
}
