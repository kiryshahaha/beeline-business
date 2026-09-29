"use client";

import { useState } from "react";
import {
  IconCheck,
  IconUrgent,
  IconWrench,
  IconTicket,
  IconClose,
  IconCar,
  IconBicycle,
  IconWalk,
  IconTransit,
  IconOffice,
} from "./Markers/MapIcons";
import PointTooltip from "./Markers/PointTooltip";
import styles from "./MapComponent.module.css";

export const ClusterPoint = ({
  isCluster,
  count = 0,
  urgentCount = 0,
  type,
  id,
  status = "planned",
  isUrgent = false,
  transportType = "car",
  isOnLine = true,
  label,
  title,
  address,
  selected = false,
  hasActiveSelection = false,
}) => {
  const [isHovered, setIsHovered] = useState(false);

  // 1. Отображение суперкластера (ТОЛЬКО здесь отображаются цифры — количество объектов в группе)
  if (isCluster) {
    const hasUrgent = urgentCount > 0;
    const clusterSizeClass =
      count >= 30 ? styles.clusterMarker_large : count >= 10 ? styles.clusterMarker_medium : "";

    return (
      <div
        className={styles.markerContainer}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <button
          type="button"
          className={`${styles.clusterMarker} ${clusterSizeClass} ${selected ? styles.selectedMarker : ""}`}
          data-urgent={hasUrgent}
          aria-label={`Группа из ${count} объектов`}
        >
          {count}
        </button>

        {isHovered && !hasActiveSelection && (
          <PointTooltip
            tag={`Группа (${count})`}
            tagVariant={hasUrgent ? "urgent" : "stop"}
            text={`Объектов в группе: ${count}`}
            subtext={hasUrgent ? `${urgentCount} требуют срочного внимания` : "Нажмите для приближения"}
          />
        )}
      </div>
    );
  }

  // 2. Отображение индивидуальной точки (БЕЗ цифр-ID, ТОЛЬКО понятные иконки статуса и типа)
  let displayContent = null;
  let tagVariant = "planned";
  let tag = "Заявка";
  const ticketIdLabel = label?.startsWith("#") ? label : `#${id}`;

  if (type === "ticket") {
    if (isUrgent) {
      tagVariant = "urgent";
      tag = "Срочно";
      displayContent = <IconUrgent size={14} />;
    } else if (status === "in_progress") {
      tagVariant = "in_progress";
      tag = "В работе";
      displayContent = <IconWrench size={13} />;
    } else if (status === "completed") {
      tagVariant = "completed";
      tag = "Выполнено";
      displayContent = <IconCheck size={13} />;
    } else if (status === "wont_fix") {
      tagVariant = "wont_fix";
      tag = "Отменена";
      displayContent = <IconClose size={12} />;
    } else {
      tagVariant = "planned";
      tag = "Запланирована";
      displayContent = <IconTicket size={13} />;
    }
  } else if (type === "worker") {
    tagVariant = "worker";
    tag = isOnLine ? "На линии" : "Офлайн";

    if (transportType === "bicycle") {
      displayContent = <IconBicycle size={14} />;
    } else if (transportType === "walking") {
      displayContent = <IconWalk size={14} />;
    } else if (transportType === "public_transport") {
      displayContent = <IconTransit size={14} />;
    } else {
      displayContent = <IconCar size={14} />;
    }
  } else if (type === "office") {
    tagVariant = "office";
    tag = "Офис";
    displayContent = <IconOffice size={15} />;
  }

  const tooltipTag = type === "ticket" ? `${ticketIdLabel} • ${tag}` : tag;

  return (
    <div
      className={styles.markerContainer}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <button
        type="button"
        className={`${styles.geoMarker} ${styles[`geoMarker_${type}`] || ""} ${
          selected ? styles.selectedMarker : ""
        }`}
        data-status={status}
        data-urgent={Boolean(isUrgent)}
        data-online={Boolean(isOnLine)}
        aria-label={label || title}
      >
        {displayContent}
      </button>

      {isHovered && !selected && !hasActiveSelection && (
        <PointTooltip
          tag={tooltipTag}
          tagVariant={tagVariant}
          text={title || label}
          subtext={address}
        />
      )}
    </div>
  );
};
