import { Popup } from "@vis.gl/react-maplibre";

export default function OfficePopup({ data, longitude, latitude, onClose }) {
  if (!data) return null;

  return (
    <Popup
      longitude={longitude}
      latitude={latitude}
      closeButton={false}
      closeOnClick={false}
      anchor="right"
      onClose={onClose}
    >
      <div
        style={{
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          position: "relative",
        }}
      >
        {/* Кнопка закрытия */}
        <button
          onClick={onClose}
          style={{
            position: "absolute",
            top: -4,
            right: -4,
            width: 28,
            height: 28,
            border: "none",
            background: "transparent",
            color: "#8c8c8c",
            fontSize: 22,
            lineHeight: 1,
            cursor: "pointer",
            padding: 0,
          }}
        >
          ×
        </button>

        {/* Заголовок */}
        <div style={{ paddingRight: 25, marginBottom: 12 }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: "#1f2937",
            }}
          >
            Офис #{data.id}
          </div>

          <div
            style={{
              marginTop: 3,
              fontSize: 13,
              color: "#6b7280",
            }}
          >
            Информация о местоположении
          </div>
        </div>

        {/* Адрес */}
        <div
          style={{
            padding: "10px 12px",
            background: "#f5f7fa",
            borderRadius: 8,
            marginBottom: 14,
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "#8c8c8c",
              marginBottom: 3,
            }}
          >
            АДРЕС
          </div>

          <div
            style={{
              fontSize: 14,
              fontWeight: 500,
              color: "#262626",
            }}
          >
            {data.address || "Адрес не указан"}
          </div>
        </div>

        {/* Данные */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "10px 16px",
          }}
        >
          <InfoItem label="Город" value={data.city} />
          <InfoItem label="Район" value={data.district} />
          <InfoItem label="Улица" value={data.street} />
          <InfoItem label="Дом" value={data.building_number} />
          <InfoItem label="Корпус" value={data.block} />
          <InfoItem label="Подъезд" value={data.entrance_number} />
          <InfoItem label="Этаж" value={data.floor} />
          <InfoItem label="Квартира" value={data.apartment} />
        </div>

        {/* Координаты */}
        <div
          style={{
            marginTop: 14,
            paddingTop: 10,
            borderTop: "1px solid #f0f0f0",
            fontSize: 11,
            color: "#8c8c8c",
          }}
        >
          {Number(latitude).toFixed(6)}, {Number(longitude).toFixed(6)}
        </div>
      </div>
    </Popup>
  );
}

function InfoItem({ label, value }) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: "#8c8c8c",
          marginBottom: 2,
        }}
      >
        {label}
      </div>

      <div
        style={{
          fontSize: 13,
          color: "#262626",
          minHeight: 18,
        }}
      >
        {value || "—"}
      </div>
    </div>
  );
}
