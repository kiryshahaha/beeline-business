"use client";

import { useState } from "react";
import {
  IconCheck,
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

  // 1. Отображение суперкластера
  if (isCluster) {
    const hasUrgent = urgentCount > 0;

    return (
      <div
        className={styles.markerContainer}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <button
          type="button"
          className={`${styles.clusterMarker} ${selected ? styles.selectedMarker : ""}`}
          data-urgent={hasUrgent}
          aria-label={`Кластер из ${count} объектов`}
        >
          {count}
        </button>

        {isHovered && !hasActiveSelection && (
          <PointTooltip
            tag={`${count}`}
            tagVariant="stop"
            text={`Объектов в группе: ${count}`}
            subtext={hasUrgent ? `(${urgentCount} срочных)` : undefined}
          />
        )}
      </div>
    );
  }

  // 2. Отображение индивидуальной точки
  let displayContent = null;
  let tagVariant = "planned";
  let tag = "Ожидает";
  const ticketNum = label?.match(/#(\d+)/)?.[1] || id;

  if (type === "ticket") {
    if (isUrgent) {
      tagVariant = "urgent";
      tag = "Срочно";
      displayContent = ticketNum;
    } else if (status === "in_progress") {
      tagVariant = "in_progress";
      tag = "В работе";
      displayContent = ticketNum;
    } else if (status === "completed") {
      tagVariant = "completed";
      tag = "Выполнено";
      displayContent = <IconCheck size={13} />;
    } else if (status === "wont_fix") {
      tagVariant = "wont_fix";
      tag = "Отменена";
      displayContent = ticketNum;
    } else {
      tagVariant = "planned";
      tag = "Ожидает";
      displayContent = ticketNum;
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
    displayContent = <IconOffice size={14} />;
  }

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
        title={label || title}
      >
        {displayContent}
      </button>

      {isHovered && !selected && !hasActiveSelection && (
        <PointTooltip
          tag={tag}
          tagVariant={tagVariant}
          text={title || label}
          subtext={address}
        />
      )}
    </div>
  );
};
