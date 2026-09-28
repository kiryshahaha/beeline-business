import { Popup } from "@vis.gl/react-maplibre";
import styles from "./MapComponent.module.css";
import { IconOffice } from "./Markers/MapIcons";

export default function OfficePopup({ data, longitude, latitude, onClose }) {
  if (!data) return null;

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      offset={16}
      closeButton
      closeOnClick={false}
      onClose={onClose}
    >
      <div className={styles.geoPopup}>
        <div className={styles.popupHeader}>
          <span className={styles.popupEyebrow}>Офис / База</span>
          <span className={styles.popupTag}>ID #{data.office_id ?? data.id}</span>
        </div>

        <h3 className={styles.popupTitle}>{data.office_name || "Офис обслуживания"}</h3>
        <p className={styles.popupAddress}>
          <IconOffice size={13} style={{ flexShrink: 0, marginTop: 2, opacity: 0.7 }} />
          <span>{data.address || "Адрес не указан"}</span>
        </p>

        <p className={styles.popupCoordinates}>
          {Number(latitude).toFixed(5)}, {Number(longitude).toFixed(5)}
        </p>

        <div className={styles.popupMeta}>
          {data.city && <span className={styles.popupTag}>{data.city}</span>}
          {data.district && <span className={styles.popupTag}>{data.district}</span>}
        </div>
      </div>
    </Popup>
  );
}
